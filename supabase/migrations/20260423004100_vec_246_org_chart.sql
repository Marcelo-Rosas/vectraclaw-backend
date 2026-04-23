-- Migration: Org Chart and Hierarchical Sectors
-- Issue: VEC-246
-- Schema: vectraclip

-- 1. Hierarquia de Setores
ALTER TABLE vectraclip.sipoc_sectors
    ADD COLUMN IF NOT EXISTS parent_sector_id UUID REFERENCES vectraclip.sipoc_sectors(id) ON DELETE SET NULL;

-- 2. Tabela de Cargos/Posições
CREATE TABLE IF NOT EXISTS vectraclip.sipoc_positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES vectraclip.sipoc_companies(id) ON DELETE CASCADE,
    sector_id UUID REFERENCES vectraclip.sipoc_sectors(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    reports_to_id UUID REFERENCES vectraclip.sipoc_positions(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Vincular Processo ao Cargo Responsável
ALTER TABLE vectraclip.sipoc_processes
    ADD COLUMN IF NOT EXISTS position_id UUID REFERENCES vectraclip.sipoc_positions(id) ON DELETE SET NULL;

-- 4. Trigger updated_at
CREATE TRIGGER set_updated_at_sipoc_positions
    BEFORE UPDATE ON vectraclip.sipoc_positions
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

-- 5. RLS habilitado (políticas definidas em migration separada)
ALTER TABLE vectraclip.sipoc_positions ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE vectraclip.sipoc_positions IS 'Representa o organograma corporativo vinculado ao SIPOC';
COMMENT ON COLUMN vectraclip.sipoc_sectors.parent_sector_id IS 'ID do setor pai para hierarquia organizacional';
