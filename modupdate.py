import os
import json
import json5
import zipfile
import requests
import time
import argparse
from urllib.parse import quote
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.console import Console

MOD_FOLDER = "./.minecraft/mods"
CACHE_FILE = "modrinth_cache.json"
LOADER = "fabric"
MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "DemonGamDev/modupdater/1.0.0 (demongamdev@gmail.com)"

console = Console()
HEADERS = {"User-Agent": USER_AGENT}
RATE_LIMIT_DELAY = 0.25 #seconds between api calls

def parse_args():
    parser = argparse.ArgumentParser(description="Modrinth Mod Auto-Updater")
    parser.add_argument("--version", required=True,help="Minecraft version, e.g. 1.20.1")
    return parser.parse_args()

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent = 2)

def get_mod_id_from_jar(jar_path):
    try:
        with zipfile.ZipFile(jar_path) as z:
            candidates = [name for name in z.namelist() if name.endswith("fabric.mod.json")]
            if not candidates:
                return None
            candidates.sort(key=lambda x: x.count("/"))
            # Try reading as UTF-8, fallback to latin-1 if needed
            try:
                with z.open(candidates[0]) as f:
                    data = json5.load(f)
                    return data.get("id")
            except UnicodeDecodeError:
                with z.open(candidates[0]) as f:
                    text = f.read().decode("latin-1", errors="replace")
                    try:
                        data = json5.loads(text)
                        return data.get("id") # type: ignore
                    except json.JSONDecodeError:
                        console.print(f"[red]Invalid JSON in {jar_path} ({candidates[0]})[/red]")
            except json.JSONDecodeError:
                console.print(f"[red]Invalid JSON in {jar_path} ({candidates[0]})[/red]")
    except Exception as e:
        console.print(f"[red]Failed to read {jar_path}: {e}[/red]")
    return None

def prompt_for_slug(mod_id, jar_name): 
    console.print(f"\n[bold yellow] Unknown mod ID: [/bold yellow] {mod_id}")
    console.print(f"[cyan] File:[/cyan] {jar_name}")
    slug = input("Enter the Modrinth project slug (or type 'skip'): ").strip()
    return slug if slug.lower() != "skip" else None

def get_latest_version(slug, game_version):
    time.sleep(RATE_LIMIT_DELAY)
    url = f"{MODRINTH_API}/project/{quote(slug)}/version"
    params = {
        "loaders": f'["{LOADER}"]',
        "game_versions": f'["{game_version}"]'
    }
    try:
        resp = requests.get(url,params=params,headers=HEADERS)
        if resp.status_code == 200:
            versions = resp.json()
            if versions:
                return versions[0]
    except Exception as e:
        print(f"Error fetching versions for {slug}: {e}")

def download_file(url, dest):
    if os.path.exists(dest):
        return "I"
    try:
        resp = requests.get(url)
        if resp.status_code == 200:
            with open(dest, "wb") as f:
                f.write(resp.content)
            return True
    except Exception as e:
        print(f"Download failed: {e}")
    return False    

def validate_mod_id(new_jar, expected_id):
    new_id = get_mod_id_from_jar(new_jar)
    return new_id, new_id == expected_id

def main():
    args = parse_args()
    game_version = args.version

    cache = load_cache()
    updated_mods = []

    files = [f for f in os.listdir(MOD_FOLDER) if f.endswith(".jar")]
    if not files:
        console.print("[yellow]No .jar files founds in mod folder.[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        transient=True
    ) as progress:
        task = progress.add_task("Processing mods...", total=len(files))
        for file in files:
            path = os.path.join(MOD_FOLDER, file)  
            mod_id = get_mod_id_from_jar(path)
            if not mod_id:
                progress.console.print(f"[red] Skipping unreadable mod: {file}[/red]")
                progress.update(task, advance=1)
            slug = cache.get(mod_id)
            if not slug:
                slug = prompt_for_slug(mod_id,file)
                if not slug:
                    progress.update(task,advance=1)
                    continue
                cache[mod_id] = slug
                save_cache(cache)
            version_data = get_latest_version(slug, game_version)
            if not version_data:
                progress.console.print(f"[yellow] No compatible version found for {slug}[/yellow]") 
                progress.update(task, advance=1)
                continue
            file_info = version_data["files"][0]
            download_url = file_info["url"]
            filename = file_info["filename"]
            dest_path = os.path.join(MOD_FOLDER, filename)

            progress.console.print(f"[green] Updating {slug}[/green]")
            downresp = download_file(download_url, dest_path)
            if downresp == "I":
                progress.console.print(f"[red] No updates needed for {slug}[/red]")
                progress.update(task, advance=1)
                continue
            if not downresp:
                progress.console.print(f"[red] Failed to download {slug}[/red]")
                progress.update(task, advance=1)
                continue
            new_id, valid = validate_mod_id(dest_path,mod_id)
            if not valid:
                progress.console.print(f"[yellow] Mod ID changed: {mod_id} ➡️ {new_id}[/yellow]")
                cache[new_id] = slug
                del cache[mod_id]
                save_cache(cache)
            
            os.remove(path)
            updated_mods.append((file, filename))
            progress.update(task, advance=1)
    console.print("\n[bold green] Update Summary:[/bold green]")
    if not updated_mods:
        console.print("[dim]No mods were updated.[/dim]")
    else:
        for old, new in updated_mods:
            console.print(f"[blue]{old}[/blue] ➡️ [green]{new}[/green]")

if __name__ == "__main__":
    main()
