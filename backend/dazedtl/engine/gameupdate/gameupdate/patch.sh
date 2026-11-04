#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(pwd)"
CONFIG_FILE="$SCRIPT_DIR/patch-config.txt"
STATE_FILE="$SCRIPT_DIR/previous_patch_sha.txt"
API_HEADERS=( -H "User-Agent: GameUpdate/1.0" )

# Where applying a patch keeps what it changed: on the game's own drive, so
# setting a game file aside is a rename that needs no space. DazedTL keeps it
# out of patches (gameupdate_local in project_preparation.py).
UNDO_DIR="$SCRIPT_DIR/undo"
UNDO_JOURNAL="$UNDO_DIR/journal.txt"
UNDO_MOVED=0
APPLYING=0

# Puts the game back as it was before a patch copy that did not finish, from
# its journal, newest change first: moves each game file it set aside back,
# removes each file it added, and each folder it added once that is empty.
# Each step checks what is there first, so running it again after it stopped
# finishes it. Fails when a file can't be put back, keeping the journal for
# the next run.
undo_patch() {
    local lines=() line kind relative number path i left=0
    if [ -f "$UNDO_JOURNAL" ]; then
        echo "Putting the game back as it was..."
        # A line cut short, when the run ended while writing it, has no
        # newline, so read skips it; the change it names was never made.
        while IFS= read -r line; do
            lines+=( "$line" )
        done < "$UNDO_JOURNAL"
        for ((i = ${#lines[@]} - 1; i >= 0; i--)); do
            kind="${lines[i]%% *}"
            relative="${lines[i]#* }"
            if [ "$kind" = moved ]; then
                number="${relative%% *}"
                relative="${relative#* }"
            fi
            [ -n "$relative" ] || continue
            path="$ROOT_DIR/$relative"
            if [ "$kind" = moved ]; then
                if [ -e "$UNDO_DIR/$number" ] || [ -L "$UNDO_DIR/$number" ]; then
                    if ! { rm -f "$path" && mv -f "$UNDO_DIR/$number" "$path"; }; then
                        echo "GameUpdate could not put back $relative."
                        left=1
                    fi
                fi
            elif [ -d "$path" ] && [ ! -L "$path" ]; then
                # Another program may have put files in it since; an empty
                # folder changes nothing for the game.
                rmdir "$path" 2> /dev/null || true
            elif [ -e "$path" ] || [ -L "$path" ]; then
                if ! rm -f "$path"; then
                    echo "GameUpdate could not remove $relative."
                    left=1
                fi
            fi
        done
        if [ "$left" -ne 0 ]; then
            echo "ERROR: GameUpdate could not put the game back fully. Close the game, then run GameUpdate again to finish putting it back."
            return 1
        fi
        # Once the journal is gone the game is as it was; the rest of the
        # folder is only left over.
        rm -f "$UNDO_JOURNAL"
        echo "The game was left as it was before this update."
    fi
    rm -rf "$UNDO_DIR"
}

# Copies patch file $1 to $2, relative to the game, after writing the change
# to undo_patch's journal: the game file it replaces is moved aside, and the
# file and each folder it adds are listed.
copy_patch_file() {
    local source="$1" relative="$2" folder i
    local folders=()
    folder="$(dirname "$relative")"
    while [ "$folder" != . ] && [ ! -d "$ROOT_DIR/$folder" ]; do
        folders+=( "$folder" )
        folder="$(dirname "$folder")"
    done
    for ((i = ${#folders[@]} - 1; i >= 0; i--)); do
        printf 'added %s\n' "${folders[i]}" >> "$UNDO_JOURNAL" || return 1
        mkdir "$ROOT_DIR/${folders[i]}" || return 1
    done
    if [ -d "$ROOT_DIR/$relative" ]; then
        echo "ERROR: This patch has a file where the game has a folder: $relative"
        return 1
    fi
    if [ -e "$ROOT_DIR/$relative" ] || [ -L "$ROOT_DIR/$relative" ]; then
        printf 'moved %s %s\n' "$UNDO_MOVED" "$relative" >> "$UNDO_JOURNAL" || return 1
        mv -f "$ROOT_DIR/$relative" "$UNDO_DIR/$UNDO_MOVED" || return 1
        UNDO_MOVED=$((UNDO_MOVED + 1))
    else
        printf 'added %s\n' "$relative" >> "$UNDO_JOURNAL" || return 1
    fi
    cp -f "$source" "$ROOT_DIR/$relative"
}

# Temporary folders and the downloaded ZIP go however the run ends, closed
# window and Ctrl+C included; a patch stopped while it is applied is undone,
# with further signals and output errors, such as a closed terminal's, no
# longer stopping that.
TEMP_PATHS=()
remove_temp_paths() {
    local path
    trap '' INT TERM HUP
    set +e
    if [ "$APPLYING" -eq 1 ]; then
        undo_patch
    fi
    for path in "${TEMP_PATHS[@]}"; do
        rm -rf "$path"
    done
    rm -f "$ROOT_DIR/repo.zip"
}
trap remove_temp_paths EXIT
trap 'exit 130' INT TERM HUP

check_dependency() {
  if ! command -v "$1" > /dev/null 2>&1; then
    echo "Error: '$1' is not installed. Please install it using 'pkg install $1'."
    exit 1
  fi
}

# Run a Windows .exe. On Linux always go through wine (never rely on binfmt,
# which can hang waiting on wineserver / GUI). On Windows / Git Bash, exec directly.
run_windows_exe() {
    local exe="$1"
    shift
    case "$(uname -s)" in
        Linux*)
            if ! command -v wine > /dev/null 2>&1; then
                echo "ERROR: wine is required to run $(basename "$exe") on Linux."
                return 1
            fi
            ( cd "$ROOT_DIR" && WINEDEBUG=-all wine "$exe" "$@" )
            ;;
        *)
            ( cd "$ROOT_DIR" && "$exe" "$@" )
            ;;
    esac
}

# Check for jq, unzip, and curl
check_dependency jq
check_dependency unzip
check_dependency curl

# An update stopped partway, such as by a power cut, is undone first.
undo_patch || exit 1

# Check if CONFIG_FILE exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file '$CONFIG_FILE' not found! Assuming no patching needed."
    exit 0
fi

# Convert line endings to Unix format
sed -i 's/\r$//' "$CONFIG_FILE"

# Debug information
echo "Root directory: $ROOT_DIR"
echo "Config file path: $CONFIG_FILE"

# Read configuration from file
# shellcheck disable=SC1090
. "$CONFIG_FILE"

# Defaults for older configs that only set username/repo/branch.
forge="${forge:-${provider:-gitlab}}"
host="${host:-}"
username="${username:-${owner:-${org:-}}}"
repo="${repo:-}"
branch="${branch:-}"

if [ -z "$username" ]; then
    echo "ERROR: 'username=' is missing in gameupdate/patch-config.txt"
    exit 1
fi
if [ -z "$repo" ]; then
    echo "ERROR: 'repo=' is missing in gameupdate/patch-config.txt"
    exit 1
fi
if [ -z "$branch" ]; then
    echo "ERROR: 'branch=' is missing in gameupdate/patch-config.txt"
    exit 1
fi

normalize_forge() {
    local raw
    raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$raw" in
        ''|gitlab|gl|gitgud) echo gitlab ;;
        github|gh) echo github ;;
        forgejo|gitea|fj|codeberg) echo forgejo ;;
        *)
            echo "ERROR: Unknown forge='$1'. Use gitlab, github, or forgejo." >&2
            return 1
            ;;
    esac
}

FORGE_KIND="$(normalize_forge "$forge")" || exit 1

# Strip scheme / path from host if a user pasted a full URL.
HOST_NAME="$(printf '%s' "$host" | sed -E 's#^https?://##; s#/.*##; s#[[:space:]]##g')"
if [ -z "$HOST_NAME" ]; then
    case "$FORGE_KIND" in
        gitlab) HOST_NAME="gitgud.io" ;;
        github) HOST_NAME="github.com" ;;
        forgejo) HOST_NAME="codeberg.org" ;;
    esac
fi

WEB_BASE="https://${HOST_NAME}"
case "$FORGE_KIND" in
    gitlab) API_BASE="${WEB_BASE}/api/v4" ;;
    github)
        if [ "$HOST_NAME" = "github.com" ]; then
            API_BASE="https://api.github.com"
        else
            API_BASE="${WEB_BASE}/api/v3"
        fi
        ;;
    forgejo) API_BASE="${WEB_BASE}/api/v1" ;;
esac

API_HEADERS=( -H "User-Agent: GameUpdate/1.0" )
if [ "$FORGE_KIND" = "gitlab" ]; then
    # GitGud lets an app's request past its Cloudflare challenge when it
    # carries this header, whatever its value; GitLab itself ignores it.
    API_HEADERS+=( -H "X-Gitlab-Token: dazedtl-gameupdate" )
fi
if [ "$FORGE_KIND" = "github" ]; then
    API_HEADERS+=( -H "Accept: application/vnd.github+json" )
fi

owner_enc=$(jq -nr --arg s "$username" '$s | @uri')
repo_enc=$(jq -nr --arg s "$repo" '$s | @uri')
branch_enc=$(jq -nr --arg b "$branch" '$b | @uri')
project_enc=$(jq -nr --arg ns "$username" --arg rp "$repo" '$ns + "/" + $rp | @uri')

resolve_latest_sha() {
    case "$FORGE_KIND" in
        gitlab)
            curl -fsSL "${API_HEADERS[@]}" \
                "${API_BASE}/projects/${project_enc}/repository/branches/${branch_enc}" \
                | jq -r '.commit.id'
            ;;
        github)
            curl -fsSL "${API_HEADERS[@]}" \
                "${API_BASE}/repos/${owner_enc}/${repo_enc}/commits/${branch_enc}" \
                | jq -r '.sha'
            ;;
        forgejo)
            curl -fsSL "${API_HEADERS[@]}" \
                "${API_BASE}/repos/${owner_enc}/${repo_enc}/branches/${branch_enc}" \
                | jq -r '.commit.id'
            ;;
    esac
}

archive_url_for_sha() {
    local sha_enc
    sha_enc=$(jq -nr --arg s "$1" '$s | @uri')
    case "$FORGE_KIND" in
        gitlab)
            echo "${API_BASE}/projects/${project_enc}/repository/archive.zip?sha=${sha_enc}"
            ;;
        github)
            echo "${API_BASE}/repos/${owner_enc}/${repo_enc}/zipball/${sha_enc}"
            ;;
        forgejo)
            echo "${API_BASE}/repos/${owner_enc}/${repo_enc}/archive/${sha_enc}.zip"
            ;;
    esac
}

# Git's own smart HTTP serves the same branch when the forge's API or archive
# download is refused, as GitGud's Cloudflare rule did on 2026-11-02.
GIT_URL="${WEB_BASE}/${username}/${repo}.git"

# No prompt for a login a public patch never needs: a missing repository
# fails instead of waiting on a credential helper.
git_quiet() {
    GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git -c credential.helper= "$@"
}

require_git() {
    if command -v git > /dev/null 2>&1; then
        return 0
    fi
    local install="your package manager's git package"
    if command -v steamos-readonly > /dev/null 2>&1; then
        # SteamOS keeps its system read-only, so pacman alone fails there.
        install="sudo steamos-readonly disable && sudo pacman-key --init && sudo pacman-key --populate archlinux holo && sudo pacman -S git && sudo steamos-readonly enable (in Desktop Mode, after setting a password with passwd)"
    elif command -v apt-get > /dev/null 2>&1; then
        install="sudo apt install git"
    elif command -v dnf > /dev/null 2>&1; then
        install="sudo dnf install git"
    elif command -v pacman > /dev/null 2>&1; then
        install="sudo pacman -S git"
    elif command -v zypper > /dev/null 2>&1; then
        install="sudo zypper install git"
    elif command -v pkg > /dev/null 2>&1; then
        install="pkg install git"
    fi
    echo "ERROR: GameUpdate needs Git to download this patch, and Git is not installed."
    echo "       Install it with: $install"
    echo "       Then run GameUpdate again."
    exit 1
}

git_latest_sha() {
    git_quiet ls-remote "$GIT_URL" "refs/heads/${branch}" | awk 'NR == 1 { print $1 }'
}

# The branch's commit from Git's ref advertisement, a plain GET that needs no
# Git: sets latest_patch_sha, or stops when the answer is definite (offline,
# no such public repository or branch). Returns 1 when the forge gave no
# usable answer, such as a challenge page, so Git itself has to ask.
read_advertised_sha() {
    local body code
    body="$(mktemp)"
    TEMP_PATHS+=( "$body" )
    code="$(curl -sS -o "$body" -w '%{http_code}' --max-time 60 \
        -H "User-Agent: GameUpdate/1.0" \
        "${GIT_URL}/info/refs?service=git-upload-pack" 2>/dev/null)" || true
    case "$code" in
        200)
            # pkt-lines: four hex digits of length, then "<sha> <ref>"; a ref
            # line can follow a flush (0000) or carry capabilities after a NUL.
            latest_patch_sha="$(tr '\0' '\n' < "$body" | awk -v ref="refs/heads/${branch}" '
                $2 == ref {
                    field = $1
                    size = length(field) < 68 ? 40 : 64
                    print substr(field, length(field) - size + 1)
                    exit
                }')"
            if ! [[ "$latest_patch_sha" =~ ^[0-9a-f]{40,64}$ ]]; then
                echo "ERROR: Branch '${branch}' was not found in ${WEB_BASE}/${username}/${repo}."
                exit 1
            fi
            return 0
            ;;
        401|404)
            echo "ERROR: ${WEB_BASE}/${username}/${repo} was not found or is not public. GameUpdate needs no account; ask the translator to check the repository."
            exit 1
            ;;
        ''|000)
            echo "ERROR: Could not reach ${HOST_NAME}. Check your internet connection, then run GameUpdate again."
            exit 1
            ;;
        5??)
            echo "ERROR: ${HOST_NAME} is having problems (HTTP ${code}). Try GameUpdate again later."
            exit 1
            ;;
    esac
    return 1
}

echo "Pulling patch from ${WEB_BASE}/${username}/${repo} (${FORGE_KIND}, branch: ${branch})"

RETRIES="${GAMEUPDATE_DL_ATTEMPTS:-2}"
if ! [[ "$RETRIES" =~ ^[1-9][0-9]*$ ]]; then
    RETRIES=2
fi

retry_cmd() {
    local name="$1"
    shift
    local attempt=1
    while true; do
        if "$@"; then
            return 0
        fi
        if [ "$attempt" -ge "$RETRIES" ]; then
            echo "$name failed after $attempt attempt(s)." >&2
            return 1
        fi
        echo "$name failed ($attempt/$RETRIES), retrying..." >&2
        attempt=$((attempt + 1))
        sleep 2
    done
}

# Get the latest hash: the forge's API first, Git when the API fails.
echo "Getting latest commit SHA hash"
latest_patch_sha=""
download_method=archive
attempt=1
while true; do
    if latest_patch_sha="$(resolve_latest_sha)"; then
        latest_patch_sha="$(printf '%s' "$latest_patch_sha" | tr -d '[:space:]')"
        if [ -n "$latest_patch_sha" ] && [ "$latest_patch_sha" != "null" ]; then
            break
        fi
    fi
    if [ "$attempt" -ge "$RETRIES" ]; then
        echo "Resolve latest patch SHA failed after $attempt attempt(s); reading the branch from the repository instead."
        download_method=git
        break
    fi
    echo "Resolve latest patch SHA failed ($attempt/$RETRIES), retrying..."
    attempt=$((attempt + 1))
    sleep 2
done
if [ "$download_method" = "git" ] && ! read_advertised_sha; then
    require_git
    latest_patch_sha="$(retry_cmd "Ask Git for the latest patch commit" git_latest_sha)" || true
    latest_patch_sha="$(printf '%s' "$latest_patch_sha" | tr -d '[:space:]')"
    if ! [[ "$latest_patch_sha" =~ ^[0-9a-f]{40,64}$ ]]; then
        echo "ERROR: Git could not read branch '${branch}' from ${GIT_URL}."
        exit 1
    fi
fi

# --------------------------------------------------------
# PRE-SETUP: Wolf Data.wolf -> loose Data/ (before patch copy)
# --------------------------------------------------------
wolf_loose_data_ready() {
    local data_dir="$1"
    [ -d "$data_dir" ] || return 1
    [ -f "$data_dir/BasicData/CommonEvent.dat" ] && return 0
    [ -f "$data_dir/CommonEvent.dat" ] && return 0
    if compgen -G "$data_dir/*.mps" > /dev/null 2>&1; then
        return 0
    fi
    if compgen -G "$data_dir/BasicData/*.dat" > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

is_wolf_game() {
    local name data_dir
    for name in Data.wolf data.wolf; do
        [ -f "$ROOT_DIR/$name" ] && return 0
    done
    for data_dir in "$ROOT_DIR/Data" "$ROOT_DIR/data"; do
        wolf_loose_data_ready "$data_dir" && return 0
    done
    return 1
}

find_uberwolf_cli() {
    if [ -f "$ROOT_DIR/UberWolfCli.exe" ]; then
        echo "$ROOT_DIR/UberWolfCli.exe"
        return 0
    fi
    if [ -f "$ROOT_DIR/gameupdate/UberWolfCli.exe" ]; then
        echo "$ROOT_DIR/gameupdate/UberWolfCli.exe"
        return 0
    fi
    return 1
}

retire_data_wolf() {
    local data_wolf="$1"
    local bak="${data_wolf}.bak"
    if [ ! -f "$data_wolf" ]; then
        return 0
    fi
    if [ ! -e "$bak" ]; then
        echo "[Pre-Setup] Retiring $(basename "$data_wolf") -> $(basename "$bak")"
        mv -f "$data_wolf" "$bak"
    else
        echo "[Pre-Setup] Removing leftover $(basename "$data_wolf") so loose Data/ takes priority"
        rm -f "$data_wolf"
    fi
}

invoke_wolf_pre_setup() {
    local data_wolf=""
    local name
    for name in Data.wolf data.wolf; do
        if [ -f "$ROOT_DIR/$name" ]; then
            data_wolf="$ROOT_DIR/$name"
            break
        fi
    done
    [ -n "$data_wolf" ] || return 0

    local data_dir="$ROOT_DIR/Data"
    if [ ! -d "$data_dir" ] && [ -d "$ROOT_DIR/data" ]; then
        data_dir="$ROOT_DIR/data"
    fi

    if wolf_loose_data_ready "$data_dir"; then
        retire_data_wolf "$data_wolf"
        return 0
    fi

    local cli
    cli="$(find_uberwolf_cli || true)"
    if [ -z "$cli" ]; then
        echo "[Pre-Setup] Data.wolf found but UberWolfCli.exe is missing."
        echo "            Unpack Data.wolf once with UberWolf (https://github.com/Sinflower/UberWolf/releases), then run GameUpdate again."
        return 0
    fi

    echo "[Pre-Setup] Unpacking Data.wolf with UberWolfCli (one-time)..."
    if ! run_windows_exe "$cli" -o "$data_wolf"; then
        echo "[Pre-Setup] ERROR: UberWolfCli unpack failed."
        return 0
    fi

    local unpacked="$ROOT_DIR/Data"
    if ! wolf_loose_data_ready "$unpacked"; then
        unpacked="$ROOT_DIR/data"
    fi
    if ! wolf_loose_data_ready "$unpacked"; then
        local alt
        for alt in data.wolf~ Data.wolf~ Data~ data~; do
            if [ -d "$ROOT_DIR/$alt" ]; then
                echo "[Pre-Setup] Promoting $alt -> Data/"
                rm -rf "$ROOT_DIR/Data"
                mv -f "$ROOT_DIR/$alt" "$ROOT_DIR/Data"
                unpacked="$ROOT_DIR/Data"
                break
            fi
        done
    fi

    if wolf_loose_data_ready "$unpacked"; then
        retire_data_wolf "$data_wolf"
        echo "[Pre-Setup] Wolf Data/ is ready for patching."
    else
        echo "[Pre-Setup] ERROR: Unpack finished but loose Data/ still looks empty."
    fi
}

invoke_wolf_pre_setup

# --------------------------------------------------------
# PRE-SETUP: Ensure SRPG data and patch structure exists
# Run Steps 1 and 2 BEFORE pulling repo patch to avoid overwriting updates
# 1) Unpack once if data folder doesn't exist (and data.dts does)
# 2) Create Patch once if patch folder doesn't exist
# --------------------------------------------------------
UNPACKER="$ROOT_DIR/SRPG_Unpacker.exe"
if [ -f "$ROOT_DIR/data.dts" ]; then
    if [ -f "$UNPACKER" ]; then
        echo "[Pre-Setup] Running SRPG_Unpacker preparation steps..."

        # Step 1: Unpack (once), mirroring patch.ps1: unpack if no data/ or no data/project.dat
        if [ ! -d "$ROOT_DIR/data" ] || [ ! -f "$ROOT_DIR/data/project.dat" ]; then
            if [ -f "$ROOT_DIR/data.dts" ]; then
                echo "[Pre-Setup] Step 1: Unpacking data.dts -> data"
                run_windows_exe "$UNPACKER" -o data data.dts || echo "[Pre-Setup] ERROR: Unpack failed."
            else
                echo "[Pre-Setup] Step 1: Skipping unpack (no data folder and no data.dts found)."
            fi
        else
            echo "[Pre-Setup] Step 1: data folder exists; skipping unpack."
        fi

        # Step 2: Create Patch (once)
        if [ ! -d "$ROOT_DIR/patch" ]; then
            if [ -f "$ROOT_DIR/data/project.dat" ]; then
                echo "[Pre-Setup] Step 2: Creating patch from data/project.dat"
                run_windows_exe "$UNPACKER" ./data/project.dat -c || echo "[Pre-Setup] ERROR: Create Patch failed."
            else
                echo "[Pre-Setup] Step 2: Skipping create patch (data/project.dat not found)."
            fi
        else
            echo "[Pre-Setup] Step 2: patch folder exists; skipping create."
        fi
    else
        echo "[Pre-Setup] SRPG_Unpacker.exe not found in root; skipping pre-setup steps."
    fi
fi

download_archive() {
    echo "Downloading latest patch..."
    archive_url="$(archive_url_for_sha "$latest_patch_sha")"
    if ! retry_cmd "Download archive with curl" \
        curl -fSL --progress-bar "${API_HEADERS[@]}" \
        "$archive_url" \
        -o "$ROOT_DIR/repo.zip"; then
        echo "Download failed!"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi
    # A challenge or error page in place of the archive.
    if [ "$(head -c 2 "$ROOT_DIR/repo.zip")" != "PK" ]; then
        echo "The download is not a ZIP archive."
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi
}

# Fetches only the branch's newest commit and packs its files the way the
# forges' archives do: git archive, so export-ignore rules apply, under one
# root folder, with no line-ending conversion.
download_with_git() {
    echo "Downloading latest patch with Git..."
    local repo_dir
    repo_dir=$(mktemp -d)
    TEMP_PATHS+=( "$repo_dir" )
    if ! git_quiet init -q "$repo_dir" \
        || ! retry_cmd "Fetch the patch with Git" \
            git_quiet -C "$repo_dir" fetch --depth 1 --no-tags "$GIT_URL" "refs/heads/${branch}"; then
        echo "Git download failed!"
        rm -rf "$repo_dir"
        return 1
    fi
    local fetched
    fetched="$(git_quiet -C "$repo_dir" rev-parse FETCH_HEAD)"
    # Git LFS's own filter stays off, so its files come out as the pointer
    # files the unpacked patch is checked for.
    if ! git_quiet -C "$repo_dir" -c core.autocrlf=false -c core.eol=lf \
        -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false \
        archive --format=zip --prefix=patch/ -o "$ROOT_DIR/repo.zip" FETCH_HEAD; then
        echo "Git could not pack the patch!"
        rm -rf "$repo_dir"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi
    rm -rf "$repo_dir"
    latest_patch_sha="$fetched"
}

# Unpacks repo.zip into a new temporary folder, TMP_EX.
extract_zip() {
    TMP_EX=$(mktemp -d)
    TEMP_PATHS+=( "$TMP_EX" )
    echo "Extracting..."
    if ! unzip -qo "$ROOT_DIR/repo.zip" -d "$TMP_EX"; then
        echo "Extraction failed!"
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi
}

download_extract() {
    if [ "$download_method" = "archive" ]; then
        if ! download_archive || ! extract_zip; then
            echo "The archive could not be downloaded or unpacked; trying Git instead."
            require_git
            download_method=git
        fi
    fi
    if [ "$download_method" = "git" ]; then
        require_git
        if ! download_with_git || ! extract_zip; then
            return 1
        fi
    fi

    inner=""
    for d in "$TMP_EX"/*; do
        if [ -d "$d" ]; then
            inner="$d"
            break
        fi
    done
    if [ -z "$inner" ]; then
        echo "Archive had no root folder!"
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi

    # Files kept in Git LFS arrive as small pointer files from Git, and from
    # a forge whose archives leave LFS out; never put those in a game.
    lfs_pointer="$(find "$inner" -type f -size -1024c \
        -exec grep -l -x -F 'version https://git-lfs.github.com/spec/v1' {} + 2>/dev/null | head -n 1)" || true
    if [ -n "$lfs_pointer" ]; then
        echo "ERROR: This patch keeps files in Git LFS, such as ${lfs_pointer#"$inner"/}, which GameUpdate can't download. Download it from ${WEB_BASE}/${username}/${repo} instead."
        exit 1
    fi

    wolf_patch=0
    if is_wolf_game; then
        wolf_patch=1
        # Stage UberWolfCli before unpack so Data.wolf -> Data/ happens before
        # English patch files are copied on top. This stays outside the
        # patch's undo: the loose Data/ it unpacks is the same game, which a
        # later run would unpack again.
        for cli_name in UberWolfCli.exe UberWolfCli.LICENSE.txt; do
            if [ -f "$inner/$cli_name" ] && [ ! -f "$ROOT_DIR/$cli_name" ]; then
                cp -f "$inner/$cli_name" "$ROOT_DIR/$cli_name"
            fi
        done
        invoke_wolf_pre_setup
    fi

    echo "Applying patch..."
    mkdir -p "$UNDO_DIR"
    : > "$UNDO_JOURNAL"
    UNDO_MOVED=0
    APPLYING=1
    copy_failed=0
    while IFS= read -r -d '' patch_file; do
        relative_path="${patch_file#"$inner"/}"
        file_name="${patch_file##*/}"
        if [ "$wolf_patch" -ne 1 ] && \
           { [ "$file_name" = "UberWolfCli.exe" ] || [ "$file_name" = "UberWolfCli.LICENSE.txt" ]; }; then
            continue
        fi
        if ! copy_patch_file "$patch_file" "$relative_path"; then
            copy_failed=1
            break
        fi
    done < <(find "$inner" -type f -print0)
    if [ "$copy_failed" -ne 0 ]; then
        echo "Patch application failed!"
        APPLYING=0
        undo_patch || true
        rm -rf "$TMP_EX"
        rm -f "$ROOT_DIR/repo.zip"
        return 1
    fi
    APPLYING=0
    rm -f "$UNDO_JOURNAL"
    rm -rf "$UNDO_DIR"

    # --------------------------------------------------------
    # POST-APPLY: Run Steps 3 and 4 after patch files are merged
    # (Must finish before "Cleaning up" so a slow wine/SRPG step is not
    # mistaken for a hung cleanup - matches patch.ps1 order.)
    # --------------------------------------------------------
    UNPACKER="$ROOT_DIR/SRPG_Unpacker.exe"
    if [ -f "$ROOT_DIR/data.dts" ]; then
        if [ -f "$UNPACKER" ]; then
            echo "Running SRPG_Unpacker apply/pack steps..."

            if [ -f "$ROOT_DIR/data/project.dat" ]; then
                echo "Step 3: Applying patch to data/project.dat"
                run_windows_exe "$UNPACKER" ./data/project.dat -a || echo "ERROR: Apply Patch failed."
            else
                echo "ERROR: data/project.dat not found; cannot apply patch."
            fi

            if [ -d "$ROOT_DIR/data" ]; then
                echo "Step 4: Packing data -> data.dts"
                run_windows_exe "$UNPACKER" -o data.dts data || echo "WARNING: Pack failed."
            else
                echo "Step 4: Skipping pack (data folder not found)."
            fi
        else
            echo "SRPG_Unpacker.exe not found in root; skipping SRPG patch steps."
        fi
    fi

    # Retire Data.wolf if loose Data/ is ready after the patch copy.
    invoke_wolf_pre_setup

    echo "Cleaning up..."
    rm -rf "$TMP_EX"
    rm -f "$ROOT_DIR/repo.zip"
    # Legacy / accidental leftovers from older patchers.
    rm -rf "$ROOT_DIR/_patch_extract_tmp"
    shopt -s nullglob
    for stale in "$ROOT_DIR"/dazedmtl_patch_*.zip; do
        rm -f "$stale"
    done
    shopt -u nullglob

    echo "$latest_patch_sha" > "$STATE_FILE"
    echo "Done."
}

# Check if previous_patch_sha.txt exists in gameupdate
if [ ! -f "$STATE_FILE" ]; then
    echo "No saved patch version yet (first run); comparing with remote..."
    download_extract
else
    previous_patch_sha=$(tr -d '[:space:]' < "$STATE_FILE")

    if [ "$latest_patch_sha" != "$previous_patch_sha" ]; then
        echo "Update found! Patching..."
        download_extract
    else
        echo "Already up to date (matches latest patch commit)."
    fi
fi
