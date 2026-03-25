# Gerador de QR Code para Documentos

Projeto em Python que permite carregar um documento, gerar um QR code e abrir esse documento diretamente na propria aplicacao.

## Arquitetura

- `Render` hospeda a app Flask
- `Supabase Storage` guarda os ficheiros enviados e o logotipo opcional
- `Supabase Postgres` guarda os metadados dos documentos
- O QR code aponta para a rota da tua app, e nao para um site de terceiros
- O historico completo fica numa area privada protegida por autenticacao basica

## Funcionalidades

- Upload de documento
- QR code simples
- QR code com logotipo central opcional
- Download do QR code em PNG
- Historico privado em `/admin`

## Requisitos

- Python 3.11 recomendado
- Conta no Render
- Conta no Supabase

## Instalar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Cria um ficheiro `.env` com base em `.env.example` ou define estas variaveis no PowerShell:

```powershell
$env:APP_BASE_URL='http://127.0.0.1:5000'
$env:SUPABASE_URL='https://SEU-PROJETO.supabase.co'
$env:SUPABASE_SERVICE_ROLE_KEY='SUA_SERVICE_ROLE_KEY'
$env:SUPABASE_BUCKET='documents'
$env:ADMIN_USERNAME='seu-utilizador'
$env:ADMIN_PASSWORD='sua-password-forte'
```

## Executar localmente

```bash
python app.py
```

Depois abre:

```text
http://127.0.0.1:5000
```

## Configurar o Supabase

### 1. Criar o projeto

1. Entra no Supabase.
2. Cria um novo projeto.
3. Guarda o `Project URL` e a `service_role key`.

### 2. Criar o bucket

1. Vai a `Storage`.
2. Cria um bucket chamado `documents`.
3. Marca o bucket como `Private`.

### 3. Criar ou atualizar a tabela

No `SQL Editor`, executa o conteudo de [supabase_setup.sql](d:/kldn/Project/QR-Code/supabase_setup.sql).

## Hospedar no Render

### 1. Enviar para o GitHub

1. Cria um repositório no GitHub.
2. Faz upload deste projeto.

### 2. Criar o Web Service

1. Entra no Render.
2. Clica em `New +`.
3. Escolhe `Web Service`.
4. Liga o repositório GitHub.

### 3. Configurar o deploy

Usa estes valores:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app --bind 0.0.0.0:$PORT
```

Tambem podes usar [render.yaml](d:/kldn/Project/QR-Code/render.yaml).

### 4. Adicionar variaveis de ambiente no Render

No painel da app no Render, adiciona:

```text
APP_BASE_URL=https://nome-da-tua-app.onrender.com
SUPABASE_URL=https://SEU-PROJETO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=SUA_SERVICE_ROLE_KEY
SUPABASE_BUCKET=documents
ADMIN_USERNAME=seu-utilizador
ADMIN_PASSWORD=sua-password-forte
```

### 5. Fazer deploy

1. Guarda as configuracoes.
2. Espera o deploy terminar.
3. Abre a app no URL `onrender.com`.
4. Faz upload de um documento.
5. Testa o QR code.
6. Acede a `https://nome-da-tua-app.onrender.com/admin` para ver o historico privado.

## Notas importantes

- A pagina inicial deixou de mostrar o historico publicamente.
- A area `/admin` pede autenticacao HTTP Basic.
- O bucket deve ser privado.
- A `service_role key` deve ficar apenas no backend e nunca no frontend.
- O logotipo opcional deve ser uma imagem.
