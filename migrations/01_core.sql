-- =============================================================================
-- MIGRATION 01 — Núcleo de OfertasCL
-- =============================================================================
-- Catálogo (stores/categories/products/listings) + serie de precios + salida del
-- detector (baselines/candidates/posts) + observabilidad del scraping.
--
-- La decisión de diseño que atraviesa todo el schema: los TRES precios chilenos
-- se guardan por separado y solo `price_effective` alimenta el detector.
--   price_effective → el que paga cualquiera, sin tarjeta de la casa
--   price_card      → con plástico propio; se muestra, no se compara
--   price_normal    → el "antes" tachado que declara la tienda; NO se cree,
--                     se guarda como evidencia para medir cuánto miente cada una
--
-- IMPORTANT: idempotente (IF NOT EXISTS / ON CONFLICT). Segura de re-ejecutar.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Tiendas y taxonomía interna
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stores (
    id             SERIAL PRIMARY KEY,
    slug           VARCHAR(40)  NOT NULL UNIQUE,
    name           VARCHAR(80)  NOT NULL,
    base_url       TEXT         NOT NULL,
    adapter        VARCHAR(60)  NOT NULL,
    rate_limit_rps NUMERIC(4,2) NOT NULL DEFAULT 0.5,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT stores_rate_limit_check CHECK (rate_limit_rps > 0)
);

-- `discount_threshold` es el θ por categoría del detector. Arranca con valores
-- de partida razonables y se RECALIBRA contra la curva precisión-volumen que
-- emite pricing/backtest.py — no se deja fijo a ojo.
CREATE TABLE IF NOT EXISTS categories (
    id                 SERIAL PRIMARY KEY,
    slug               VARCHAR(60) NOT NULL UNIQUE,
    name               VARCHAR(80) NOT NULL,
    parent_id          INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    discount_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.20,
    CONSTRAINT categories_threshold_check
        CHECK (discount_threshold > 0 AND discount_threshold < 1)
);

-- Qué categorías raspa cada tienda y con qué llave. `store_key` es opaco a
-- propósito: para Falabella es un término de búsqueda, para Sodimac un path de
-- categoría (su /search descarta el query string y pierde la paginación).
CREATE TABLE IF NOT EXISTS store_categories (
    store_id    INTEGER NOT NULL REFERENCES stores(id)     ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    store_key   TEXT    NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (store_id, category_id, store_key)
);

-- -----------------------------------------------------------------------------
-- Identidad de producto (cross-store) y listings (producto EN una tienda)
-- -----------------------------------------------------------------------------
-- `products` agrupa el mismo producto vendido en varias tiendas. El detector NO
-- depende de este agrupamiento (usa la historia propia de cada listing); sirve
-- para enriquecer el mensaje ("$X más barato que en Paris"). Un match malo
-- degrada el copy, nunca la señal.
CREATE TABLE IF NOT EXISTS products (
    id            SERIAL PRIMARY KEY,
    canonical_key VARCHAR(120) NOT NULL UNIQUE,
    brand         VARCHAR(80),
    model         VARCHAR(120),
    gtin          VARCHAR(14),
    name          TEXT,
    category_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_gtin
    ON products(gtin) WHERE gtin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_brand_model
    ON products(brand, model) WHERE brand IS NOT NULL AND model IS NOT NULL;

CREATE TABLE IF NOT EXISTS listings (
    id                SERIAL PRIMARY KEY,
    store_id          INTEGER NOT NULL REFERENCES stores(id)     ON DELETE CASCADE,
    product_id        INTEGER          REFERENCES products(id)   ON DELETE SET NULL,
    category_id       INTEGER          REFERENCES categories(id) ON DELETE SET NULL,
    store_sku         VARCHAR(64) NOT NULL,
    url               TEXT        NOT NULL,
    name_raw          TEXT        NOT NULL,
    brand_raw         VARCHAR(80),
    image_url         TEXT,
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT listings_store_sku_unique UNIQUE (store_id, store_sku)
);

CREATE INDEX IF NOT EXISTS idx_listings_product   ON listings(product_id)
    WHERE product_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_listings_category  ON listings(category_id);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen_at);

-- -----------------------------------------------------------------------------
-- Serie de precios — la tabla que crece. Particionada por mes.
-- -----------------------------------------------------------------------------
-- Muestreo 2×/día. `price_effective` es NOT NULL: una observación sin precio
-- pagable no es una observación, se descarta en el adaptador antes de llegar acá
-- (un cero corrompería la baseline de por vida).
CREATE TABLE IF NOT EXISTS price_points (
    listing_id      INTEGER     NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    observed_at     TIMESTAMPTZ NOT NULL,
    price_effective NUMERIC(12,2) NOT NULL,
    price_normal    NUMERIC(12,2),
    price_card      NUMERIC(12,2),
    in_stock        BOOLEAN     NOT NULL DEFAULT TRUE,
    claimed_discount VARCHAR(16),
    PRIMARY KEY (listing_id, observed_at),
    CONSTRAINT price_points_effective_check CHECK (price_effective > 0)
) PARTITION BY RANGE (observed_at);

CREATE INDEX IF NOT EXISTS idx_price_points_observed
    ON price_points(observed_at);

-- Particiones: se crean por adelantado con un helper idempotente. El runner de
-- migraciones llama a `ensure_price_partitions()` en cada arranque, así que
-- nunca falta la partición del mes en curso ni la del siguiente.
CREATE OR REPLACE FUNCTION ensure_price_partitions(months_ahead INTEGER DEFAULT 2)
RETURNS void AS $$
DECLARE
    start_month DATE := date_trunc('month', NOW())::DATE;
    i           INTEGER;
    from_date   DATE;
    to_date     DATE;
    part_name   TEXT;
BEGIN
    FOR i IN 0..months_ahead LOOP
        from_date := start_month + (i || ' month')::INTERVAL;
        to_date   := from_date + INTERVAL '1 month';
        part_name := 'price_points_' || to_char(from_date, 'YYYYMM');
        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part_name) THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF price_points FOR VALUES FROM (%L) TO (%L)',
                part_name, from_date, to_date);
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

SELECT ensure_price_partitions(2);

-- -----------------------------------------------------------------------------
-- Baselines — recomputadas a diario sobre observaciones CON STOCK
-- -----------------------------------------------------------------------------
-- `p50_60d` es el "precio de verdad" del SKU: contra esto se mide el descuento,
-- nunca contra el price_normal declarado por la tienda.
CREATE TABLE IF NOT EXISTS listing_baselines (
    listing_id   INTEGER PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    p50_60d      NUMERIC(12,2) NOT NULL,
    p10_60d      NUMERIC(12,2) NOT NULL,
    min_60d      NUMERIC(12,2) NOT NULL,
    n_points     INTEGER       NOT NULL,
    n_days       INTEGER       NOT NULL,
    -- TRUE si en d−21..d−3 hubo un alza ≥15% sobre p50 que persistió ≥5 días:
    -- la firma del patrón "inflo y después descuento".
    ramp_flag    BOOLEAN       NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_listing_baselines_computed
    ON listing_baselines(computed_at);

-- -----------------------------------------------------------------------------
-- Salida del detector
-- -----------------------------------------------------------------------------
-- TODO candidato se persiste, aprobado o rechazado, con su motivo. Es el dataset
-- que permite tunear los umbrales con evidencia en vez de a ojo.
CREATE TABLE IF NOT EXISTS deal_candidates (
    id            SERIAL PRIMARY KEY,
    listing_id    INTEGER     NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    price         NUMERIC(12,2) NOT NULL,
    p50_60d       NUMERIC(12,2) NOT NULL,
    discount_real NUMERIC(5,4)  NOT NULL,
    score         NUMERIC(6,3),
    verdict       VARCHAR(12)   NOT NULL,
    reject_reason VARCHAR(32),
    -- Etiqueta a posteriori que escribe pricing/backtest.py con la ventana +30d.
    -- Una oferta real es un pozo temporal (el precio vuelve a subir); un precio
    -- inflado-normalizado es un escalón permanente.
    outcome_label VARCHAR(12),
    outcome_at    TIMESTAMPTZ,
    CONSTRAINT deal_candidates_verdict_check
        CHECK (verdict IN ('accepted', 'rejected')),
    CONSTRAINT deal_candidates_outcome_check
        CHECK (outcome_label IS NULL OR outcome_label IN ('real', 'fake', 'unknown')),
    CONSTRAINT deal_candidates_reject_check
        CHECK ((verdict = 'rejected') = (reject_reason IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_deal_candidates_listing
    ON deal_candidates(listing_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_deal_candidates_accepted
    ON deal_candidates(detected_at DESC) WHERE verdict = 'accepted';
CREATE INDEX IF NOT EXISTS idx_deal_candidates_pending_outcome
    ON deal_candidates(detected_at) WHERE outcome_label IS NULL;

-- Idempotencia de publicación, mismo patrón que `telegram_signal_posts` en
-- signalsTrading: correr el daemon dos veces no duplica mensajes.
CREATE TABLE IF NOT EXISTS deal_posts (
    id                  SERIAL PRIMARY KEY,
    candidate_id        INTEGER NOT NULL REFERENCES deal_candidates(id) ON DELETE CASCADE,
    tier_id             INTEGER NOT NULL,
    telegram_message_id BIGINT,
    posted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT deal_posts_candidate_tier_unique UNIQUE (candidate_id, tier_id)
);

CREATE INDEX IF NOT EXISTS idx_deal_posts_posted ON deal_posts(posted_at DESC);

-- -----------------------------------------------------------------------------
-- Observabilidad del scraping — alimenta el canario diario
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_runs (
    id          SERIAL PRIMARY KEY,
    store_id    INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    category_id INTEGER          REFERENCES categories(id) ON DELETE SET NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status      VARCHAR(12) NOT NULL DEFAULT 'running',
    items_seen  INTEGER NOT NULL DEFAULT 0,
    items_ok    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    CONSTRAINT scrape_runs_status_check
        CHECK (status IN ('running', 'ok', 'partial', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_store_started
    ON scrape_runs(store_id, started_at DESC);

COMMIT;
