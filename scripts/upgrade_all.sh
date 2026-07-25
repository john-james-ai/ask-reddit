#!/usr/bin/env bash
#
# upgrade_all.sh — upgrade every package in the active environment.
#   1. conda updates all conda-installed packages
#   2. pip updates ONLY pip-installed (pypi) packages, leaving conda's alone
#
# Run with the target env activated, e.g.:  conda activate sciven && ./upgrade_all.sh
#
set -euo pipefail

echo "=================================================="
echo " Environment: ${CONDA_DEFAULT_ENV:-<none active>}"
echo " Python:      $(command -v python)"
echo "=================================================="

if [[ -z "${CONDA_DEFAULT_ENV:-}" ]]; then
  echo "ERROR: no conda env is active. Run 'conda activate <env>' first." >&2
  exit 1
fi

echo
echo ">>> [1/3] Upgrading all CONDA-installed packages ..."
conda update --all -y

echo
echo ">>> [2/3] Upgrading all PIP-installed (pypi) packages, skipping conda's ..."
pip_pkgs=$(conda list | awk '$4=="pypi"{print $1}')
if [[ -z "$pip_pkgs" ]]; then
  echo "    (no pip-installed packages found — nothing to do)"
else
  echo "    Packages to upgrade:"
  echo "$pip_pkgs" | sed 's/^/      - /'
  echo "$pip_pkgs" | xargs -r python -m pip install -U
fi

echo
echo ">>> [3/3] Verifying dependency consistency ..."
python -m pip check || echo "    (pip check reported conflicts — review above)"

echo
echo "=================================================="
echo " Done."
echo "=================================================="
