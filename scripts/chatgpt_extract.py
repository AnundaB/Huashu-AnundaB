#!/usr/bin/env python3
"""
chatgpt_extract.py — ChatGPT conversation-to-Markdown extractor.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_USER_DATA_DIR = os.path.join(REPO_ROOT, "outputs", "browser-profiles", "chrome-profile12-clone")
DEFAULT_PROFILE_NAME = "Profile 12"


def extract_conversation_id(url: str) -> str | None:
    """Extracts the conversation UUID from a ChatGPT URL."""
    match = re.search(r"/c/([a-f0-9\-]{36})", url)
    if match:
        return match.group(1)
    return None


def clean_title(title: str) -> str:
    """Cleans up document title by removing ChatGPT suffix."""
    title = title.strip()
    if title.endswith(" - ChatGPT"):
        title = title[:-10].strip()
    return title or "ChatGPT Conversation"


def parse_export(json_path: str, conversation_id: str) -> tuple[dict | None, str | None]:
    """Parses official data export conversations.json for the specified conversation id."""
    if not os.path.exists(json_path):
        return None, f"Export file not found: {json_path}"

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, f"Failed to parse JSON: {e}"

    if not isinstance(data, list):
        return None, "Invalid conversations.json structure (expected an array)."

    convo = None
    for item in data:
        if item.get("id") == conversation_id:
            convo = item
            break

    if not convo:
        return None, f"Conversation ID '{conversation_id}' not found in export file."

    return convo, None


def linearize_conversation(conversation: dict) -> list[dict]:
    """Extracts a linear chronological message path from a tree structure in export."""
    mapping = conversation.get("mapping", {})
    
    # Find leaf nodes (nodes with no children)
    leaves = []
    for node_id, node in mapping.items():
        if not node.get("children"):
            leaves.append(node_id)

    # Find the leaf node corresponding to the latest branch
    best_leaf = None
    latest_time = -1
    for leaf_id in leaves:
        curr = leaf_id
        curr_time = -1
        while curr in mapping:
            node = mapping[curr]
            msg = node.get("message")
            if msg and msg.get("create_time"):
                curr_time = max(curr_time, msg.get("create_time"))
                break
            curr = node.get("parent")
        if curr_time > latest_time:
            latest_time = curr_time
            best_leaf = leaf_id

    # Trace path from best_leaf back to the root
    path = []
    curr = best_leaf
    while curr in mapping:
        node = mapping[curr]
        path.append(node)
        curr = node.get("parent")

    path.reverse()

    # Build linear message list
    messages = []
    for node in path:
        msg = node.get("message")
        if not msg:
            continue
        role = msg.get("author", {}).get("role")
        if role not in ("user", "assistant", "system", "tool"):
            continue

        # Extract content parts
        content = msg.get("content", {})
        parts = content.get("parts", [])
        text_parts = []
        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                text_parts.append(part.get("text", ""))

        text = "".join(text_parts).strip()
        if text:
            messages.append({
                "id": msg.get("id") or node.get("id") or "",
                "role": role,
                "text": text
            })

    return messages


def run_export_extraction(json_path: str, conversation_id: str, output_dir: str) -> int:
    """Runs extraction using the official exported JSON file."""
    convo, err = parse_export(json_path, conversation_id)
    if err:
        sys.stderr.write(f"[error] {err}\n")
        return 1

    title = clean_title(convo.get("title") or f"ChatGPT Conversation {conversation_id}")
    messages = linearize_conversation(convo)
    
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    md_filename = f"{stamp}-chatgpt-{conversation_id}.md"
    md_filepath = os.path.join(output_dir, md_filename)

    # Write Markdown content
    write_markdown_file(
        url="none",
        conversation_id=conversation_id,
        title=title,
        message_count=len(messages),
        status="success",
        extraction_method="official_json_export",
        messages=messages,
        notes=["Extracted via official conversations.json export."],
        output_path=md_filepath
    )

    print(f"saved Markdown path: {md_filepath}")
    print(f"status: success")
    print(f"message_count: {len(messages)}")
    return 0


def write_markdown_file(
    url: str,
    conversation_id: str,
    title: str,
    message_count: int,
    status: str,
    extraction_method: str,
    messages: list[dict],
    notes: list[str],
    output_path: str
):
    """Formats and writes the markdown file structure."""
    notes_section = "\n".join([f"- {n}" for n in notes]) if notes else "- None"
    
    # Build conversation section
    convo_blocks = []
    for msg in messages:
        role = msg["role"].capitalize()
        text = msg["text"]
        convo_blocks.append(f"### {role}\n\n{text}")

    convo_content = "\n\n".join(convo_blocks)

    content = f"""---
source_type: chatgpt_conversation
url: {url}
conversation_id: {conversation_id}
title: {title}
message_count: {message_count}
status: {status}
extraction_method: {extraction_method}
---

# ChatGPT Conversation: {title}

## Metadata

- **URL**: {url}
- **Conversation ID**: {conversation_id}
- **Message Count**: {message_count}
- **Status**: {status}
- **Extraction Method**: {extraction_method}

## Conversation

{convo_content if convo_content else "No conversation content found."}

## Notes

{notes_section}
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def run_browser_extraction(
    url: str,
    output_dir: str,
    user_data_dir: str,
    profile_name: str,
    full_mode: bool = False,
    scroll_timeout: int = 120,
    stable_passes: int = 1,
    debug_scroll: bool = False
) -> int:
    """Launches persistence Chrome profile, scrolls the ChatGPT DOM, and extracts conversation."""
    conversation_id = extract_conversation_id(url) or "chat"
    
    from playwright.sync_api import sync_playwright

    print(f"[chatgpt] Using Chrome data dir: {user_data_dir}")
    print(f"[chatgpt] Using Profile: {profile_name}")
    print(f"[chatgpt] Full mode: {full_mode}")
    print(f"[chatgpt] Scroll timeout: {scroll_timeout} seconds")
    print(f"[chatgpt] Stable passes: {stable_passes}")

    status = "partial"
    reached_top = False
    reached_bottom = False
    scroll_passes = 0
    message_map = {}
    
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    md_filename = f"{stamp}-chatgpt-{conversation_id}.md"
    md_filepath = os.path.join(output_dir, md_filename)
    title = "ChatGPT Conversation"

    def save_incremental_state(current_status: str, is_timed_out: bool = False, error_msg: str = None):
        current_notes = [
            f"reached_top: {reached_top}",
            f"reached_bottom: {reached_bottom}",
            f"scroll_passes: {scroll_passes}",
            f"unique_message_count: {len(message_map)}",
            f"timeout_seconds: {scroll_timeout}"
        ]
        if is_timed_out:
            current_notes.append("Scroll to bottom timed out. Some newer messages might be missing.")
        elif error_msg:
            current_notes.append(f"Browser crash or error: {error_msg}")
        elif current_status == "partial":
            current_notes.append("Scroll to bottom timed out. Some newer messages might be missing.")
        elif current_status == "success":
            current_notes.append("Extracted successfully using browser DOM scroll extraction.")
        
        write_markdown_file(
            url=url,
            conversation_id=conversation_id,
            title=title,
            message_count=len(message_map),
            status=current_status,
            extraction_method="browser_scroll_dom",
            messages=list(message_map.values()),
            notes=current_notes,
            output_path=md_filepath
        )

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(user_data_dir),
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 950},
                ignore_default_args=[
                    "--password-store=basic",
                    "--use-mock-keychain",
                ],
                args=[
                    f"--profile-directory={profile_name}",
                    "--disable-blink-features=AutomationControlled",
                ],
                timeout=60000,
            )

            page = context.new_page()
            print(f"[chatgpt] Navigating to {url}...")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Check if logged in / wait for messages
            login_required = False
            try:
                page.wait_for_selector('[data-message-author-role]', timeout=8000)
            except Exception:
                login_required = True

            if login_required:
                print("[chatgpt] Waiting for conversation to load. Please log in or verify Cloudflare in the browser window...")
                try:
                    page.wait_for_selector('[data-message-author-role]', timeout=60000)
                    print("[chatgpt] Conversation loaded successfully!")
                except Exception:
                    sys.stderr.write("[error] Timeout waiting for conversation. Make sure you are logged in.\n")
                    context.close()
                    # Keep partial markdown before returning
                    save_incremental_state("partial", error_msg="Timeout waiting for conversation. Make sure you are logged in.")
                    return 1

            # Inject JS helper functions
            page.evaluate("""() => {
                window.__chatgpt_extract = {
                    getScrollContainer: function() {
                        const message = document.querySelector('[data-message-author-role]');
                        if (message) {
                            let parent = message.parentElement;
                            while (parent && parent !== document.body) {
                                const style = window.getComputedStyle(parent);
                                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                                    return parent;
                                }
                                parent = parent.parentElement;
                            }
                        }
                        const main = document.querySelector('main');
                        if (main) {
                            let parent = main.parentElement;
                            while (parent && parent !== document.body) {
                                const style = window.getComputedStyle(parent);
                                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                                    return parent;
                                }
                                parent = parent.parentElement;
                            }
                        }
                        return document.documentElement || document.body;
                    },
                    collectDOMMessages: function() {
                        const elements = document.querySelectorAll('[data-message-author-role]');
                        const collected = [];
                        elements.forEach(el => {
                            const role = el.getAttribute('data-message-author-role') || 'unknown';
                            const msgId = el.getAttribute('data-message-id') || '';
                            const markdownEl = el.querySelector('.markdown') || el;
                            const text = markdownEl.innerText || '';
                            if (text.trim()) {
                                collected.push({
                                    id: msgId,
                                    role: role,
                                    text: text.trim()
                                });
                            }
                        });
                        return collected;
                    },
                    scrollDownStep: function(step, currentScroll) {
                        const c = this.getScrollContainer();
                        if (!c) return { reachedBottom: true, scrollHeight: 0, scrollTop: 0, clientHeight: 0, messages: [] };
                        c.scrollTop = currentScroll;
                        const msgs = this.collectDOMMessages();
                        return {
                            reachedBottom: (c.scrollTop + c.clientHeight >= c.scrollHeight - 10),
                            scrollHeight: c.scrollHeight,
                            scrollTop: c.scrollTop,
                            clientHeight: c.clientHeight,
                            messages: msgs
                        };
                    }
                };
            }""")

            title = clean_title(page.title()) or title
            
            # Initially save whatever is on screen
            initial_msgs = page.evaluate("window.__chatgpt_extract.collectDOMMessages()")
            for m in initial_msgs:
                key = m["id"] if m["id"] else (m["role"] + "|" + m["text"])
                message_map[key] = m
            save_incremental_state("partial")

            start_time = time.time()
            timed_out = False
            stable_passes_count = 0

            while True:
                # Check for overall timeout
                if time.time() - start_time >= scroll_timeout:
                    timed_out = True
                    break

                scroll_passes += 1
                print(f"[chatgpt] Starting scroll pass {scroll_passes}...")

                keys_before_pass = set(message_map.keys())

                # --- 1. Scroll to Top until stable ---
                print(f"[chatgpt] Pass {scroll_passes}: Scrolling to top to load full history...")
                last_scroll_height = -1
                last_message_count = -1
                stable_top_checks = 0
                required_stable_top_checks = 3

                while True:
                    # Check for overall timeout
                    if time.time() - start_time >= scroll_timeout:
                        timed_out = True
                        break

                    info = page.evaluate("""() => {
                        const c = window.__chatgpt_extract.getScrollContainer();
                        if (!c) return { scrollTop: 0, scrollHeight: 0, messageCount: 0, messages: [] };
                        c.scrollTop = 0;
                        const msgs = window.__chatgpt_extract.collectDOMMessages();
                        return {
                            scrollTop: c.scrollTop,
                            scrollHeight: c.scrollHeight,
                            messageCount: msgs.length,
                            messages: msgs
                        };
                    }""")

                    # Update message_map incrementally
                    new_found_top = False
                    for m in info.get("messages", []):
                        key = m["id"] if m["id"] else (m["role"] + "|" + m["text"])
                        if key not in message_map:
                            message_map[key] = m
                            new_found_top = True

                    if new_found_top:
                        save_incremental_state("partial")

                    if debug_scroll:
                        print(f"[debug-scroll] Pass {scroll_passes} Scroll-to-top: scrollTop={info['scrollTop']}, scrollHeight={info['scrollHeight']}, messageCount={info['messageCount']}")

                    if info["scrollTop"] == 0:
                        if info["scrollHeight"] == last_scroll_height and info["messageCount"] == last_message_count:
                            stable_top_checks += 1
                        else:
                            stable_top_checks = 0
                    else:
                        stable_top_checks = 0

                    last_scroll_height = info["scrollHeight"]
                    last_message_count = info["messageCount"]

                    if stable_top_checks >= required_stable_top_checks:
                        reached_top = True
                        break

                    page.wait_for_timeout(1000)

                if timed_out:
                    break

                # --- 2. Scroll to Bottom slowly and collect ---
                print(f"[chatgpt] Pass {scroll_passes}: Scrolling down slowly and collecting messages...")
                current_scroll = 0
                step = 300

                while True:
                    # Check for overall timeout
                    if time.time() - start_time >= scroll_timeout:
                        timed_out = True
                        break

                    result = page.evaluate("""(args) => {
                        return window.__chatgpt_extract.scrollDownStep(args.step, args.currentScroll);
                    }""", {"step": step, "currentScroll": current_scroll})

                    incoming = result.get("messages", [])
                    new_found_down = False
                    for m in incoming:
                        key = m["id"] if m["id"] else (m["role"] + "|" + m["text"])
                        if key not in message_map:
                            message_map[key] = m
                            new_found_down = True

                    if new_found_down:
                        save_incremental_state("partial")

                    if debug_scroll:
                        print(f"[debug-scroll] Pass {scroll_passes} Scroll-down: scrollTop={result['scrollTop']}, scrollHeight={result['scrollHeight']}, reachedBottom={result['reachedBottom']}")

                    if result["reachedBottom"]:
                        # Confirm bottom by waiting and checking again
                        page.wait_for_timeout(1000)
                        double_check = page.evaluate("""() => {
                            const c = window.__chatgpt_extract.getScrollContainer();
                            if (c) c.scrollTop = c.scrollHeight;
                            return window.__chatgpt_extract.scrollDownStep(0, c ? c.scrollHeight : 0);
                        }""")

                        incoming = double_check.get("messages", [])
                        for m in incoming:
                            key = m["id"] if m["id"] else (m["role"] + "|" + m["text"])
                            if key not in message_map:
                                message_map[key] = m

                        save_incremental_state("partial")

                        if double_check["reachedBottom"]:
                            reached_bottom = True
                            break

                    current_scroll += step
                    page.wait_for_timeout(200)

                if timed_out:
                    break

                # --- 3. Evaluate stability of this pass ---
                keys_after_pass = set(message_map.keys())
                new_keys_discovered = keys_after_pass - keys_before_pass

                if len(new_keys_discovered) == 0:
                    stable_passes_count += 1
                    print(f"[chatgpt] Pass {scroll_passes} complete. No new messages. Stable passes: {stable_passes_count}/{stable_passes}")
                else:
                    stable_passes_count = 0
                    print(f"[chatgpt] Pass {scroll_passes} complete. Discovered {len(new_keys_discovered)} new messages. Resetting stable passes.")

                if not full_mode:
                    break

                if stable_passes_count >= stable_passes:
                    print(f"[chatgpt] Message count stabilized for {stable_passes} passes.")
                    break

            if timed_out:
                print("[chatgpt] Scroll timeout reached. Finalizing partial save...")
                status = "partial"
                save_incremental_state("partial", is_timed_out=True)
            elif reached_top and reached_bottom and (not full_mode or stable_passes_count >= stable_passes):
                status = "success"
                save_incremental_state("success")
            else:
                status = "partial"
                save_incremental_state("partial")

            print(f"saved Markdown path: {md_filepath}")
            print(f"status: {status}")
            print(f"message_count: {len(message_map)}")
            print(f"reached_top: {reached_top}")
            print(f"reached_bottom: {reached_bottom}")
            print(f"scroll_passes: {scroll_passes}")

            context.close()
            return 0 if status in ("success", "partial") else 1

    except Exception as e:
        sys.stderr.write(f"[error] Browser automation encountered an error: {e}\n")
        try:
            save_incremental_state("partial", error_msg=str(e))
        except Exception:
            pass
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract ChatGPT conversation to Markdown.")
    parser.add_argument("url_or_file", nargs="?", help="ChatGPT URL or path to conversations.json")
    parser.add_argument("--id", help="Conversation ID for export mode")
    parser.add_argument("-chatgpt-export", "--chatgpt-export", action="store_true", help="Parse official export file")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory")
    parser.add_argument("--user-data-dir", default=None, help="Custom Chrome user data directory")
    parser.add_argument("--profile-name", default=None, help="Custom Chrome profile name")
    parser.add_argument("--full", action="store_true", help="Run full extraction mode with longer timeouts and stability checks")
    parser.add_argument("--scroll-timeout", type=int, default=None, help="Scroll timeout in seconds")
    parser.add_argument("--stable-passes", type=int, default=None, help="Number of stable passes required for full mode")
    parser.add_argument("--debug-scroll", action="store_true", help="Print debug information during scrolling")
    args = parser.parse_args()

    # Determine extraction mode
    is_export = args.chatgpt_export or (args.url_or_file and args.url_or_file.endswith(".json") and args.id)
    
    output_dir = args.output_dir or os.path.join(REPO_ROOT, "outputs", "auto")
    os.makedirs(output_dir, exist_ok=True)

    if is_export:
        if not args.url_or_file:
            sys.stderr.write("[error] Please specify the path to conversations.json.\n")
            return 1
        if not args.id:
            sys.stderr.write("[error] Please specify a target --id <conversation-id>.\n")
            return 1
        return run_export_extraction(args.url_or_file, args.id, output_dir)
    else:
        url = args.url_or_file
        if not url:
            sys.stderr.write("[error] Please specify a target ChatGPT URL.\n")
            return 1
            
        full_mode = args.full
        scroll_timeout = args.scroll_timeout
        if scroll_timeout is None:
            scroll_timeout = 600 if full_mode else 120
            
        stable_passes = args.stable_passes
        if stable_passes is None:
            stable_passes = 3 if full_mode else 1
            
        user_data_dir = args.user_data_dir or DEFAULT_USER_DATA_DIR
        profile_name = args.profile_name or DEFAULT_PROFILE_NAME
        return run_browser_extraction(
            url=url,
            output_dir=output_dir,
            user_data_dir=user_data_dir,
            profile_name=profile_name,
            full_mode=full_mode,
            scroll_timeout=scroll_timeout,
            stable_passes=stable_passes,
            debug_scroll=args.debug_scroll
        )


if __name__ == "__main__":
    sys.exit(main())
