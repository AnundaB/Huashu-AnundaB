import os
import sys
import json
import csv
import shutil
import argparse
import datetime
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO_DIR = os.getenv("HUASHU_AUTO_DIR", os.path.join(REPO_ROOT, "outputs", "auto"))

IGNORED_ITEMS = {
    "index.md", "manifest.csv", "semantic_benchmarks",
    "browser-profiles", "web", "youtube", "x", "chatgpt", "github", "docs", "research", "misc",
    "Cookies", "Login Data", "_organize-plans"
}

def get_category_for_name(name: str) -> str:
    name_lower = name.lower()
    
    # research
    if any(k in name_lower for k in ["consensus", "research", "paper", "doi", "arxiv", "journal", "topic-pack"]):
        return "research"
    # chatgpt
    if any(k in name_lower for k in ["chatgpt", "chat.openai", "branch"]):
        return "chatgpt"
    # youtube
    if any(k in name_lower for k in ["youtube", "youtu.be"]):
        return "youtube"
    # x/video
    if any(k in name_lower for k in ["x-video", "/video/"]):
        return "x/video"
    # x/text
    if any(k in name_lower for k in ["x-chrome", "x.com", "twitter", "status", "-x-"]):
        return "x/text"
    # github
    if any(k in name_lower for k in ["github", "github.com", "github-com"]):
        return "github"
    # docs
    if any(k in name_lower for k in ["docs", "documentation", "cloud.google.com", "kimi-com-code-docs"]):
        return "docs"
    
    # Generic web heuristics
    if any(k in name_lower for k in [".com", ".org", "-com-", "-org-", "medium", "file-users", "google"]):
        return "web"
        
    return "misc"

def get_unique_dest_path(dest_path: Path) -> tuple[Path, bool]:
    """Returns (unique_path, was_collision)"""
    if not dest_path.exists():
        return dest_path, False
    
    stem = dest_path.stem
    suffix = dest_path.suffix
    
    counter = 1
    while True:
        new_name = f"{stem}-{counter}{suffix}"
        new_path = dest_path.with_name(new_name)
        if not new_path.exists():
            return new_path, True
        counter += 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply the organization plan")
    parser.add_argument("--dry-run", action="store_true", help="Dry run only")
    parser.add_argument("--auto-dir", type=str, default=AUTO_DIR, help="Override auto dir")
    args = parser.parse_args()

    is_apply = args.apply
    auto_dir_path = args.auto_dir

    if not os.path.exists(auto_dir_path):
        print(f"Directory not found: {auto_dir_path}")
        sys.exit(1)

    plans_dir = os.path.join(auto_dir_path, "_organize-plans")
    
    plan = []
    exclusions = []
    
    total_candidates = 0
    collision_count = 0
    
    for item in os.listdir(auto_dir_path):
        total_candidates += 1
        item_path = Path(auto_dir_path) / item
        
        # Exclude hidden files (including .env, .DS_Store)
        if item.startswith("."):
            exclusions.append({"source": item, "reason": "hidden_file"})
            continue
            
        if item in IGNORED_ITEMS:
            exclusions.append({"source": item, "reason": "ignored_item"})
            continue
        
        if "profile" in item.lower() and "chrome" in item.lower() and item_path.is_dir():
            exclusions.append({"source": item, "reason": "chrome_profile_clone"})
            continue
            
        # Unknown directories
        category = get_category_for_name(item)
        if item_path.is_dir() and category == "misc":
            exclusions.append({"source": item, "reason": "unknown_directory"})
            continue

        dest_dir = Path(auto_dir_path) / category
        dest_path = dest_dir / item
        
        dest_path, was_collision = get_unique_dest_path(dest_path)
        if was_collision:
            collision_count += 1
            
        plan.append({
            "source": item,
            "destination": f"{category}/{dest_path.name}",
            "category": category
        })

    os.makedirs(plans_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    plan_json = os.path.join(plans_dir, f"{timestamp}-plan.json")
    plan_md = os.path.join(plans_dir, f"{timestamp}-plan.md")
    
    with open(plan_json, "w", encoding="utf-8") as f:
        json.dump({
            "moves": plan,
            "exclusions": exclusions
        }, f, indent=2)

    # Generate Markdown Plan
    category_counts = {}
    for m in plan:
        category_counts[m["category"]] = category_counts.get(m["category"], 0) + 1

    md_lines = [
        f"# Output Organization Plan ({timestamp})",
        "",
        "## Summary",
        f"- **Total candidates scanned**: {total_candidates}",
        f"- **Move count**: {len(plan)}",
        f"- **Excluded count**: {len(exclusions)}",
        f"- **Collision count**: {collision_count}",
        "",
        "## Categories",
    ]
    
    for cat, count in sorted(category_counts.items()):
        md_lines.append(f"- **{cat}**: {count}")
        
    md_lines.append("")
    md_lines.append("## Sample Moves")
    for m in plan[:10]:
        md_lines.append(f"- `{m['source']}` -> `{m['destination']}`")
        
    md_lines.append("")
    md_lines.append("## Sample Exclusions")
    for e in exclusions[:10]:
        md_lines.append(f"- `{e['source']}` (Reason: {e['reason']})")
        
    md_lines.append("")
    md_lines.append("## Action")
    if not is_apply:
        md_lines.append("> **WARNING**: Dry-run mode. No files were moved.")
        md_lines.append("")
        md_lines.append("To apply this plan, run:")
        md_lines.append("```bash")
        md_lines.append("huashu -organize-auto --apply")
        md_lines.append("```")
    else:
        md_lines.append("> **SUCCESS**: Plan applied successfully.")

    with open(plan_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"Plan generated with {len(plan)} moves and {len(exclusions)} exclusions.")
    print(f"Plan JSON saved to: {plan_json}")
    print(f"Plan MD saved to:   {plan_md}")

    if not is_apply:
        print("Dry run mode. No files moved. Run with --apply to execute.")
        return

    print("Applying moves...")
    
    manifest_path = os.path.join(auto_dir_path, "manifest.csv")
    manifest_rows = []
    has_manifest = False
    
    if os.path.exists(manifest_path):
        has_manifest = True
        with open(manifest_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames:
                for row in reader:
                    manifest_rows.append(row)
            else:
                has_manifest = False
                
    for move in plan:
        src = os.path.join(auto_dir_path, move["source"])
        dst = os.path.join(auto_dir_path, move["destination"])
        
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        
        if os.path.exists(src):
            shutil.move(src, dst)
            
            if has_manifest:
                for row in manifest_rows:
                    if row.get("output_path") == move["source"]:
                        row["output_path"] = move["destination"]
                        row["category"] = move["category"]
                        row["short_category"] = move["category"].split("/")[0]
                        
    if has_manifest:
        with open(manifest_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manifest_rows)
            
    # Also rebuild index.md using output_router if possible
    try:
        sys.path.append(os.path.join(REPO_ROOT, "scripts"))
        import output_router
        if has_manifest:
            output_router.rebuild_index(manifest_rows)
    except Exception as e:
        print(f"[warn] Failed to rebuild index.md: {e}")
            
    print("Organization complete.")

if __name__ == "__main__":
    main()
