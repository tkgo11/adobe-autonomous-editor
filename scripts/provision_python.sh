#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: provision_python.sh JOB_ROOT" >&2
  exit 2
fi

JOB_ROOT="$1"
RUNTIME_DIR="$JOB_ROOT/runtime"
PYTHON_ROOT="$RUNTIME_DIR/python-base"
UV_ROOT="$RUNTIME_DIR/uv-bootstrap"
mkdir -p "$RUNTIME_DIR"

compatible_python() {
  local candidate resolved probe_dir probe_python
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if resolved=$("$candidate" -c 'import sys; assert sys.version_info >= (3,10); print(sys.executable)' 2>/dev/null); then
        # Importing venv is not sufficient on distributions that split the
        # ensurepip payload into a separate package (for example Debian's
        # python3-venv). Prove that this interpreter can create the pip-enabled
        # environment bootstrap.py will need before accepting it.
        probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/aae-python-probe.XXXXXX")
        if "$resolved" -m venv "$probe_dir/venv" >/dev/null 2>&1; then
          probe_python="$probe_dir/venv/bin/python"
          if [[ -x "$probe_python" ]] && "$probe_python" -m pip --version >/dev/null 2>&1; then
            rm -rf -- "$probe_dir"
            printf '%s\n' "$resolved"
            return 0
          fi
        fi
        rm -rf -- "$probe_dir"
      fi
    fi
  done
  return 1
}

if [[ "${AAE_IGNORE_SYSTEM_PYTHON:-0}" != "1" ]] && PYTHON=$(compatible_python); then
  printf '%s\n' "$PYTHON"
  exit 0
fi

if [[ -x "$PYTHON_ROOT/current/bin/python3" ]]; then
  printf '%s\n' "$PYTHON_ROOT/current/bin/python3"
  exit 0
fi

download() {
  local url="$1" destination="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error "$url" --output "$destination"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$destination"
  else
    echo "A system HTTP client (curl or wget) is required to bootstrap Python." >&2
    return 1
  fi
}

latest_url() {
  if command -v curl >/dev/null 2>&1; then
    curl --head --location --silent --show-error --output /dev/null --write-out '%{url_effective}' \
      "https://github.com/astral-sh/uv/releases/latest"
  else
    wget --server-response --max-redirect=10 -qO /dev/null \
      "https://github.com/astral-sh/uv/releases/latest" 2>&1 |
      awk '/^  Location:/{url=$2} END{gsub(/\r/,"",url); print url}'
  fi
}

case "$(uname -s)" in
  Darwin) OS_TARGET="apple-darwin" ;;
  Linux)
    if ldd --version 2>&1 | grep -qi musl || compgen -G '/lib/ld-musl-*.so.1' >/dev/null; then
      OS_TARGET="unknown-linux-musl"
    else
      OS_TARGET="unknown-linux-gnu"
    fi
    ;;
  *) echo "Unsupported Unix platform: $(uname -s)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) CPU_TARGET="x86_64" ;;
  arm64|aarch64) CPU_TARGET="aarch64" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

FINAL_URL=$(latest_url)
TAG=${FINAL_URL##*/}
[[ -n "$TAG" && "$TAG" != "latest" ]] || { echo "Could not resolve the latest uv release." >&2; exit 1; }
ASSET="uv-${CPU_TARGET}-${OS_TARGET}.tar.gz"
BASE="https://github.com/astral-sh/uv/releases/download/${TAG}"
DOWNLOADS="$UV_ROOT/downloads/$TAG"
ARCHIVE="$DOWNLOADS/$ASSET"
CHECKSUM="$DOWNLOADS/$ASSET.sha256"
mkdir -p "$DOWNLOADS"
download "$BASE/$ASSET" "$ARCHIVE"
download "$BASE/$ASSET.sha256" "$CHECKSUM"

EXPECTED=$(awk '{print $1}' "$CHECKSUM")
if command -v shasum >/dev/null 2>&1; then
  ACTUAL=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')
else
  ACTUAL=$(sha256sum "$ARCHIVE" | awk '{print $1}')
fi
EXPECTED_LOWER=$(printf '%s' "$EXPECTED" | tr 'A-F' 'a-f')
ACTUAL_LOWER=$(printf '%s' "$ACTUAL" | tr 'A-F' 'a-f')
[[ "$EXPECTED_LOWER" =~ ^[0-9a-f]{64}$ && "$ACTUAL_LOWER" == "$EXPECTED_LOWER" ]] || {
  echo "Checksum verification failed for $ASSET" >&2
  exit 1
}

if tar -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "Refusing unsafe uv archive paths." >&2
  exit 1
fi
EXTRACTED="$UV_ROOT/releases/$TAG"
if [[ ! -d "$EXTRACTED" ]]; then
  mkdir -p "$EXTRACTED"
  tar -xzf "$ARCHIVE" -C "$EXTRACTED"
fi
UV=$(find "$EXTRACTED" -type f -name uv -perm -u+x | head -n 1)
[[ -x "$UV" ]] || { echo "Verified uv archive did not contain an executable." >&2; exit 1; }

mkdir -p "$PYTHON_ROOT"
UV_CACHE_DIR="$RUNTIME_DIR/uv-cache" UV_PYTHON_INSTALL_DIR="$PYTHON_ROOT" \
  "$UV" python install 3.12 --install-dir "$PYTHON_ROOT" --no-bin --quiet
PYTHON=$(UV_CACHE_DIR="$RUNTIME_DIR/uv-cache" UV_PYTHON_INSTALL_DIR="$PYTHON_ROOT" \
  "$UV" python find --managed-python 3.12 --no-project)
[[ -x "$PYTHON" ]] || { echo "uv did not provision a usable Python interpreter." >&2; exit 1; }
mkdir -p "$PYTHON_ROOT/current/bin"
ln -sfn "$PYTHON" "$PYTHON_ROOT/current/bin/python3"
printf '%s\n' "$PYTHON"
