-- Bascule en 'expired' les événements dont la date limite ou la date de fin est passée.
UPDATE events
SET status = 'expired'
WHERE status = 'active'
  AND compute_event_status(start_date, end_date, deadline) = 'expired';

-- Statistiques à jour pour le planificateur (filtres status/dates + index HNSW)
ANALYZE events;
