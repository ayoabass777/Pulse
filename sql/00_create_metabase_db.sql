-- ═══════════════════════════════════════════════════════════════════════
-- Pulse — Metabase Internal Database
-- ═══════════════════════════════════════════════════════════════════════
-- Metabase stores its own metadata (dashboards, questions, users) in a
-- separate database. This script creates it so Metabase doesn't fall back
-- to H2 (which loses data on container restart).
-- ═══════════════════════════════════════════════════════════════════════

CREATE DATABASE metabase;
