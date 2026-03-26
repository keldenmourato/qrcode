from __future__ import annotations

import mimetypes
import os
import socket
import uuid
from functools import wraps
from io import BytesIO

import qrcode
from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for
from PIL import Image
from qrcode.image.pil import PilImage
from supabase import Client, create_client
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

_supabase_client: Client | None = None


def get_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def get_missing_config() -> list[str]:
    required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_BUCKET",
    ]
    return [name for name in required if not os.environ.get(name)]


def get_supabase() -> Client:
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    missing_config = get_missing_config()
    if missing_config:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing_config)}")

    _supabase_client = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    return _supabase_client


def get_bucket_name() -> str:
    return os.environ["SUPABASE_BUCKET"]


def get_admin_username() -> str | None:
    return os.environ.get("ADMIN_USERNAME")


def get_admin_password() -> str | None:
    return os.environ.get("ADMIN_PASSWORD")


def has_admin_credentials() -> bool:
    return bool(get_admin_username() and get_admin_password())


def check_admin_auth(username: str | None, password: str | None) -> bool:
    return username == get_admin_username() and password == get_admin_password()


def admin_auth_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not has_admin_credentials():
            abort(404)

        auth = request.authorization
        if not auth or not check_admin_auth(auth.username, auth.password):
            return Response(
                "Autenticacao necessaria.",
                401,
                {"WWW-Authenticate": 'Basic realm="Historico Privado"'},
            )
        return view(*args, **kwargs)

    return wrapped_view


def get_public_origin() -> str:
    base_url = os.environ.get("APP_BASE_URL")
    if base_url:
        return base_url.rstrip("/")

    host = os.environ.get("APP_HOST")
    port = os.environ.get("APP_PORT") or os.environ.get("PORT") or "5000"
    scheme = os.environ.get("APP_SCHEME")

    if host:
        resolved_scheme = scheme or ("https" if port in {"443", "10000"} or ".onrender.com" in host else "http")
        if port in {"80", "443"}:
            return f"{resolved_scheme}://{host}"
        return f"{resolved_scheme}://{host}:{port}"

    return f"http://{get_local_ip()}:{port}"


def build_access_url(document_id: str) -> str:
    return f"{get_public_origin()}{url_for('view_document', document_id=document_id)}"


def guess_category(mime_type: str) -> str:
    if not mime_type:
        return "binary"
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("text/"):
        return "text"
    return "binary"


def enrich_document(document: dict[str, str]) -> dict[str, str]:
    enriched = dict(document)
    mime_type = enriched.get("mime_type", "application/octet-stream")
    enriched["category"] = guess_category(mime_type)
    enriched["access_url"] = build_access_url(enriched["id"])
    enriched["has_logo"] = bool(enriched.get("logo_path"))
    return enriched


def list_documents(limit: int = 50) -> list[dict[str, str]]:
    response = (
        get_supabase()
        .table("documents")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = response.data or []
    return [enrich_document(row) for row in rows]


def get_document(document_id: str) -> dict[str, str] | None:
    response = (
        get_supabase()
        .table("documents")
        .select("*")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    return enrich_document(rows[0])


def upload_document_to_supabase(
    document_id: str,
    original_name: str,
    mime_type: str,
    file_bytes: bytes,
    logo_bytes: bytes | None = None,
    logo_name: str | None = None,
    logo_mime_type: str | None = None,
) -> dict[str, str]:
    extension = os.path.splitext(original_name)[1]
    storage_path = f"documents/{document_id}{extension}"
    logo_path = None

    supabase = get_supabase()
    storage = supabase.storage.from_(get_bucket_name())

    storage.upload(
        path=storage_path,
        file=file_bytes,
        file_options={
            "content-type": mime_type,
            "upsert": "false",
        },
    )

    if logo_bytes and logo_name:
        logo_extension = os.path.splitext(logo_name)[1] or ".png"
        logo_path = f"logos/{document_id}{logo_extension}"
        storage.upload(
            path=logo_path,
            file=logo_bytes,
            file_options={
                "content-type": logo_mime_type or "image/png",
                "upsert": "false",
            },
        )

    metadata = {
        "id": document_id,
        "original_name": original_name,
        "storage_path": storage_path,
        "mime_type": mime_type,
        "logo_path": logo_path,
    }
    try:
        supabase.table("documents").insert(metadata).execute()
    except Exception:
        cleanup_paths = [storage_path]
        if logo_path:
            cleanup_paths.append(logo_path)
        storage.remove(cleanup_paths)
        raise
    return enrich_document(metadata)


def download_document_bytes(document: dict[str, str]) -> bytes:
    storage_path = document["storage_path"]
    return get_supabase().storage.from_(get_bucket_name()).download(storage_path)


def download_logo_bytes(document: dict[str, str]) -> bytes | None:
    logo_path = document.get("logo_path")
    if not logo_path:
        return None
    return get_supabase().storage.from_(get_bucket_name()).download(logo_path)


def build_qr_code_bytes(content: str, logo_bytes: bytes | None = None) -> BytesIO:
    qr_image = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr_image.add_data(content)
    qr_image.make(fit=True)
    qr_image = qr_image.make_image(fill_color="black", back_color="white", image_factory=PilImage).get_image()

    if logo_bytes:
        logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        qr_image = qr_image.convert("RGBA")

        qr_width, qr_height = qr_image.size
        logo_limit = min(qr_width, qr_height) // 4
        logo.thumbnail((logo_limit, logo_limit))

        background_size = (logo.width + 20, logo.height + 20)
        logo_background = Image.new("RGBA", background_size, (255, 255, 255, 255))
        bg_position = (
            (qr_width - logo_background.width) // 2,
            (qr_height - logo_background.height) // 2,
        )
        qr_image.alpha_composite(logo_background, dest=bg_position)

        logo_position = (
            (qr_width - logo.width) // 2,
            (qr_height - logo.height) // 2,
        )
        qr_image.alpha_composite(logo, dest=logo_position)

    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


@app.route("/", methods=["GET", "POST"])
def index():
    missing_config = get_missing_config()
    latest_document = None
    error = None

    if request.method == "POST":
        if missing_config:
            error = "Configure primeiro as variaveis do Supabase antes de enviar documentos."
        else:
            uploaded_file = request.files.get("document")
            uploaded_logo = request.files.get("logo")
            if not uploaded_file or not uploaded_file.filename:
                error = "Selecione um documento antes de gerar o QR code."
            else:
                original_name = secure_filename(uploaded_file.filename)
                if not original_name:
                    error = "O nome do ficheiro nao e valido."
                else:
                    mime_type = uploaded_file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
                    file_bytes = uploaded_file.read()
                    document_id = str(uuid.uuid4())
                    logo_bytes = None
                    logo_name = None
                    logo_mime_type = None

                    if uploaded_logo and uploaded_logo.filename:
                        logo_name = secure_filename(uploaded_logo.filename)
                        logo_mime_type = uploaded_logo.mimetype or mimetypes.guess_type(logo_name)[0] or "image/png"
                        if not logo_mime_type.startswith("image/"):
                            error = "O logotipo precisa de ser uma imagem."
                        else:
                            logo_bytes = uploaded_logo.read()

                    if not error:
                        try:
                            latest_document = upload_document_to_supabase(
                                document_id=document_id,
                                original_name=original_name,
                                mime_type=mime_type,
                                file_bytes=file_bytes,
                                logo_bytes=logo_bytes,
                                logo_name=logo_name,
                                logo_mime_type=logo_mime_type,
                            )
                        except Exception as exc:
                            error = f"Nao foi possivel enviar o documento para o Supabase: {exc}"

    return render_template(
        "index.html",
        latest_document=latest_document,
        server_origin=get_public_origin(),
        missing_config=missing_config,
        has_admin_credentials=has_admin_credentials(),
        error=error,
    )


@app.route("/admin")
@admin_auth_required
def admin_history():
    try:
        documents = list_documents()
    except Exception as exc:
        return render_template("admin.html", documents=[], error=f"Nao foi possivel carregar o historico: {exc}")

    return render_template("admin.html", documents=documents, error=None)


@app.route("/document/<document_id>")
def view_document(document_id: str):
    try:
        document = get_document(document_id)
    except Exception:
        app.logger.exception("Erro ao carregar metadados do documento %s", document_id)
        abort(500)

    if not document:
        abort(404)

    text_content = None
    if document["category"] == "text":
        try:
            text_content = download_document_bytes(document).decode("utf-8", errors="replace")
        except Exception:
            app.logger.exception("Erro ao descarregar texto do documento %s", document_id)
            abort(500)

    return render_template("document.html", document=document, text_content=text_content)


@app.route("/file/<document_id>")
def get_file(document_id: str):
    try:
        document = get_document(document_id)
    except Exception:
        app.logger.exception("Erro ao carregar metadados para o ficheiro %s", document_id)
        abort(500)

    if not document:
        abort(404)

    try:
        content = download_document_bytes(document)
    except Exception:
        app.logger.exception("Erro ao descarregar ficheiro do Supabase %s", document_id)
        abort(500)

    download = request.args.get("download") == "1"
    return send_file(
        BytesIO(content),
        mimetype=document["mime_type"],
        as_attachment=download,
        download_name=document["original_name"],
    )


@app.route("/qr/<document_id>")
def get_qr_code(document_id: str):
    try:
        document = get_document(document_id)
    except Exception:
        app.logger.exception("Erro ao carregar documento para gerar QR %s", document_id)
        abort(500)

    if not document:
        abort(404)

    try:
        qr_bytes = build_qr_code_bytes(document["access_url"], download_logo_bytes(document))
    except Exception:
        app.logger.exception("Erro ao gerar imagem QR para %s com URL %s", document_id, document.get("access_url"))
        abort(500)

    download = request.args.get("download") == "1"
    return send_file(
        qr_bytes,
        mimetype="image/png",
        as_attachment=download,
        download_name=f"qr-{document_id}.png",
    )


@app.route("/latest")
def latest_document():
    try:
        documents = list_documents(limit=1)
    except Exception:
        app.logger.exception("Erro ao carregar o documento mais recente")
        abort(500)

    if not documents:
        abort(404)

    latest = documents[0]
    return redirect(url_for("view_document", document_id=latest["id"]))


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/setup")
def setup():
    missing_config = get_missing_config()
    sql_url = "https://supabase.com/dashboard/project/_/sql/new"
    bucket_name = os.environ.get("SUPABASE_BUCKET", "documents")
    return {
        "configured": not missing_config,
        "missing_config": missing_config,
        "bucket": bucket_name,
        "next_steps": [
            "Create a private Storage bucket in Supabase.",
            "Run the SQL in supabase_setup.sql.",
            "Set the required env vars in Render.",
        ],
        "sql_editor_hint": sql_url,
    }


if __name__ == "__main__":
    host = os.environ.get("APP_BIND", "0.0.0.0")
    port = int(os.environ.get("APP_PORT") or os.environ.get("PORT") or "5000")
    app.run(host=host, port=port, debug=True)
