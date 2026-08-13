# Being at the repo root, this file makes pytest put the repo on sys.path so
# `import lc` works without relying on the venv's editable install. (macOS can
# mark .venv's .pth files hidden, and Python >= 3.12.4 skips hidden .pth files.)
