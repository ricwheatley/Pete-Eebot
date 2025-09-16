-- 1. Add is_main_lift flag to wger_exercise
ALTER TABLE wger_exercise
ADD COLUMN IF NOT EXISTS is_main_lift BOOLEAN NOT NULL DEFAULT false;

-- 2. Create bridge table for assistance mapping
CREATE TABLE IF NOT EXISTS assistance_pool (
    main_exercise_id INT NOT NULL REFERENCES wger_exercise(id) ON DELETE CASCADE,
    assistance_exercise_id INT NOT NULL REFERENCES wger_exercise(id) ON DELETE CASCADE,
    PRIMARY KEY(main_exercise_id, assistance_exercise_id)
);

-- 3. Mark the Big Four
UPDATE wger_exercise SET is_main_lift = true WHERE id IN (615, 73, 184, 566);

-- 4. Seed assistance pools

-- Squat (main id = 615)
INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id) VALUES
(615, 981), (615, 977), (615, 46), (615, 984),
(615, 986), (615, 987), (615, 988), (615, 989),
(615, 909), (615, 910), (615, 901), (615, 265),
(615, 371), (615, 632);

-- Bench (main id = 73)
INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id) VALUES
(73, 83), (73, 81), (73, 923), (73, 154), (73, 475),
(73, 194), (73, 197), (73, 538), (73, 537), (73, 445),
(73, 498), (73, 386);

-- Deadlift (main id = 184)
INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id) VALUES
(184, 507), (184, 189), (184, 484), (184, 627), (184, 630),
(184, 294), (184, 365), (184, 366), (184, 364), (184, 301),
(184, 636), (184, 960), (184, 448);

-- Overhead Press (main id = 566)
INSERT INTO assistance_pool (main_exercise_id, assistance_exercise_id) VALUES
(566, 20), (566, 79), (566, 348), (566, 256), (566, 822),
(566, 829), (566, 282), (566, 694), (566, 693), (566, 571),
(566, 572), (566, 915), (566, 478);
