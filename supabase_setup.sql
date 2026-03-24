create extension if not exists pgcrypto;

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  original_name text not null,
  storage_path text not null unique,
  mime_type text not null,
  created_at timestamptz not null default now()
);

create index if not exists documents_created_at_idx
on public.documents (created_at desc);
