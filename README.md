# Pete Eebot

This repository contains a set of tools and workflows to consolidate personal fitness data from various sources, including Withings, Apple Health, and wger workout manager. It uses GitHub Actions to automate data fetching, processing, and storage, creating a personal fitness data warehouse.

-----

## Key Features

  * **Automated Data Sync:** Daily synchronization of health and fitness data from multiple platforms.
  * **Data Consolidation:** Centralizes weight, body composition, activity, sleep, and workout data into CSV and JSON formats.
  * **"Body Age" Calculation:** A daily updated "body age" is calculated based on consolidated metrics.
  * **Personalized Goal Tracking:** Accommodates individual fitness goals, nutrition plans, and progress reviews.

-----

## Data Sources and Integrations

  * **Withings:** Syncs weight, body fat, muscle mass, and water percentage data. This is achieved through OAuth integration and a daily GitHub Actions workflow.
  * **Apple Health:** Captures detailed daily activity metrics via an iOS Shortcut, including steps, heart rate, active and resting calories, and sleep data.
  * **wger:** Imports workout logs, including exercise names, categories, reps, and weight.

-----

## Repository Structure

```
.
├── .github/workflows/       # GitHub Actions workflows for data syncing
├── docs/                      # Raw and processed data from various sources
│   ├── analytics/           # Body age calculations and history
│   ├── apple/               # Apple Health data
│   ├── days/                # Consolidated daily data
│   └── withings/            # Withings data
├── integrations/            # Scripts and configuration for data integrations
│   └── withings/
├── knowledge/               # Core fitness data and plans in CSV and Markdown
└── summaries/               # Daily data summaries
```

-----

## How It Works

This system is orchestrated through a series of GitHub Actions workflows:

1.  **`withings_sync.yml`:** Runs daily to fetch weight and body composition data from the Withings API. It refreshes the OAuth token, updates the `weight_log.csv`, and stores the raw data.
2.  **`apple_sync.yml`:** Triggered by a webhook from an iOS Shortcut, this workflow processes and commits data from Apple Health. It updates `activity_log.csv`, `cardio_log.csv`, and `recovery_log.csv`.
3.  **`wger_sync.yml`:** A scheduled workflow that pulls workout data from the wger API and updates `workout_log.csv`.
4.  **`body_age.yml`:** After the data syncs, this workflow calculates a "body age" based on a composite score of recent fitness and health data. The results are logged in `body_age_log.csv`.

The `index.html` file serves as a convenient redirect handler for the Withings OAuth process, simplifying the initial setup.

-----

## Knowledge Base

The `/knowledge` directory is the heart of this repository, containing structured data and plans for a personalized fitness journey.

### Data Logs

  * **`activity_log.csv`:** Daily activity metrics.
  * **`body_age_log.csv`:** A log of the calculated "body age" over time.
  * **`cardio_log.csv`:** Heart rate data.
  * **`recovery_log.csv`:** Sleep and recovery metrics.
  * **`weight_log.csv`:** Daily weight and body composition.

### Fitness and Nutrition Plans

  * **`goals.md`:** Outlines fitness goals, including target weight and milestones.
  * **`nutrition_plan.md`:** Details the daily nutrition strategy, including fixed meals and macronutrient targets.
  * **`plan_weekly_template.md`:** A template for a weekly training plan.
  * **`gym_resources.md`:** Information on gym classes and a strength training progression plan.
