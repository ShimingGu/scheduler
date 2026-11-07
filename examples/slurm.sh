#!/bin/bash
#SBATCH --job-name=serial-scheduler
#SBATCH --time=02:00:00
#SBATCH --output=scheduler-%j.log
set -euo pipefail

# Install serial-revision-scheduler into the selected Python environment first.
# Usage: sbatch slurm.sh /absolute/path/to/scheduler.ini
# Use a distinct run_dir in the INI for each independent job.
python3 -m scheduler run --config "$1"
