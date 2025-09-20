-- Add Blaze HIIT as a stub exercise in the catalogue
INSERT INTO wger_exercise (id, uuid, name, description, is_main_lift, category_id)
VALUES (
    99999,
    '00000000-0000-0000-0000-000000099999', -- fixed UUID, any valid v4 format works
    'Blaze HIIT',
    'Fixed group class at David Lloyd (cardio/HIIT). Logged automatically at set times.',
    false,
    15  -- Cardio category
)
ON CONFLICT (id) DO NOTHING;
