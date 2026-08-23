-- The authoritative migration runner owns the transaction boundary.

ALTER TABLE assistance_pool
    ADD COLUMN IF NOT EXISTS difficulty SMALLINT NOT NULL DEFAULT 5;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'assistance_pool_difficulty_range'
    ) THEN
        ALTER TABLE assistance_pool
            ADD CONSTRAINT assistance_pool_difficulty_range
            CHECK (difficulty BETWEEN 0 AND 10) NOT VALID;
    END IF;
END $$;

ALTER TABLE assistance_pool
    VALIDATE CONSTRAINT assistance_pool_difficulty_range;

COMMENT ON COLUMN assistance_pool.difficulty IS
    '0 excludes the assistance exercise from planning; 1-10 rates easiest to hardest.';
