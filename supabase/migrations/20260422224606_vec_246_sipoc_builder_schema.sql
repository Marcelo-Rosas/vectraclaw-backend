-- Migration: SIPOC Builder Schema
-- Issue: VEC-246
-- Description: Estrutura para Empresa -> Setores -> Processos -> Componentes SIPOC (5W2H)
-- Schema: vectraclip (alinhado ao padrão do projeto — client configurado com SUPABASE_SCHEMA=vectraclip)

-- Trigger helper (idempotente)
CREATE OR REPLACE FUNCTION vectraclip.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 1. Empresas
CREATE TABLE IF NOT EXISTS vectraclip.sipoc_companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    logo_url TEXT,
    website TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Setores
CREATE TABLE IF NOT EXISTS vectraclip.sipoc_sectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES vectraclip.sipoc_companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    icon TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(company_id, slug)
);

-- 3. Processos
CREATE TABLE IF NOT EXISTS vectraclip.sipoc_processes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sector_id UUID NOT NULL REFERENCES vectraclip.sipoc_sectors(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'rascunho',
    version INTEGER DEFAULT 1,
    responsible_id UUID,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Componentes SIPOC
CREATE TABLE IF NOT EXISTS vectraclip.sipoc_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id UUID NOT NULL REFERENCES vectraclip.sipoc_processes(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    content JSONB NOT NULL,
    "order" INTEGER NOT NULL DEFAULT 0,
    validation_status TEXT DEFAULT 'verde',
    validation_notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Triggers updated_at
CREATE TRIGGER set_updated_at_sipoc_companies
    BEFORE UPDATE ON vectraclip.sipoc_companies
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

CREATE TRIGGER set_updated_at_sipoc_sectors
    BEFORE UPDATE ON vectraclip.sipoc_sectors
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

CREATE TRIGGER set_updated_at_sipoc_processes
    BEFORE UPDATE ON vectraclip.sipoc_processes
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

CREATE TRIGGER set_updated_at_sipoc_components
    BEFORE UPDATE ON vectraclip.sipoc_components
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

-- RLS habilitado (políticas definidas em migration separada)
ALTER TABLE vectraclip.sipoc_companies  ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.sipoc_sectors    ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.sipoc_processes  ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.sipoc_components ENABLE ROW LEVEL SECURITY;
