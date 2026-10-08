#!/usr/bin/env bash
# Starts DazedTL. The first run downloads the pinned Node into .runtime; the
# launcher then installs everything else and opens the app.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pause() { if [ -t 0 ]; then read -rp "Press Enter to close." _ || true; fi; }
fail() {
  echo "DazedTL could not start: $*" >&2
  pause
  exit 1
}
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) platform=linux-x64 ;;
  Linux-aarch64 | Linux-arm64) platform=linux-arm64 ;;
  Darwin-x86_64) platform=darwin-x64 ;;
  Darwin-arm64) platform=darwin-arm64 ;;
  *) fail "this system ($(uname -s) $(uname -m)) is not supported." ;;
esac
version="$(tr -d '[:space:]' < "$root/.node-version")"
name="node-v$version-$platform"
node="$root/.runtime/$name/bin/node"
if [ ! -x "$node" ]; then
  line="$(grep -F "/$name.tar.gz" "$root/scripts/runtimes.lock" || true)"
  [ -n "$line" ] || fail "there is no pinned Node for $platform."
  hash="${line%% *}"
  url="${line##* }"
  mkdir -p "$root/.runtime"
  archive="$root/.runtime/$name.tar.gz"
  echo "Downloading Node $version…"
  if command -v curl > /dev/null; then
    curl -fL --retry 3 -o "$archive" "$url" || fail "Node could not be downloaded."
  elif command -v wget > /dev/null; then
    wget -O "$archive" "$url" || fail "Node could not be downloaded."
  else
    fail "install curl or wget first."
  fi
  if command -v sha256sum > /dev/null; then
    actual="$(sha256sum "$archive")"
  else
    actual="$(shasum -a 256 "$archive")"
  fi
  if [ "${actual%% *}" != "$hash" ]; then
    rm -f "$archive"
    fail "the Node download did not match its pinned checksum. Try again."
  fi
  staging="$root/.runtime/$name.partial"
  rm -rf "$staging"
  mkdir -p "$staging"
  tar -xzf "$archive" -C "$staging" || fail "Node could not be unpacked."
  mv "$staging/$name" "$root/.runtime/$name"
  rm -rf "$staging" "$archive"
fi
"$node" "$root/scripts/start.mjs" --detach "$@" || {
  status=$?
  pause
  exit "$status"
}
