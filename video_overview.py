# video_overview.py - HTML SLIDES + CONTINUOUS AUDIO VIDEO

import os
import json
import asyncio
import re
import time
from pathlib import Path
import edge_tts
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY= os.getenv("TAVILY_API_KEY")

print("\n" + "="*70)
print("🎬 VIDEO OVERVIEW — HTML SLIDES + AUDIO")
print("="*70)

W, H = 1280, 720


# ==================== STEP 1: LOAD FILES ====================

def load_files():
    print(f"\n{'='*70}")
    print("STEP 1: LOADING FILES")
    print('='*70)

    # output/ folder mein available files dhundo
    import glob
    
    summary_files    = sorted(glob.glob("output/*_summary.txt"))
    transcript_files = sorted(glob.glob("output/*_transcript.txt"))

    if not summary_files:
        print("❌ Koi summary file nahi mili! Pehle audiotosummary.py run karo.")
        return None, None

    # User ko choose karne do agar multiple hain
    if len(summary_files) == 1:
        chosen = summary_files[0]
    else:
        print("\n📂 Multiple videos found — konsi use karein?")
        for i, f in enumerate(summary_files, 1):
            print(f"  {i}. {f}")
        choice = input("Choice: ").strip()
        idx    = int(choice) - 1
        chosen = summary_files[idx]

    # Matching transcript dhundo
    base = chosen.replace("_summary.txt","")
    transcript_path = base + "_transcript.txt"

    print(f"✅ Using: {chosen}")

    with open(chosen, "r", encoding="utf-8") as f:
        summary = f.read()

    transcript = ""
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()

    print("✅ Files loaded!")
    return summary, transcript


# ==================== STEP 2: USER OPTIONS ====================

def get_user_options():
    print(f"\n{'='*70}")
    print("SELECT OPTIONS")
    print('='*70)

    print("\n🌐 Audio language:")
    print("  1. English")
    print("  2. Hindi")
    print("  3. Hinglish")
    lc = input("Choice (1/2/3): ").strip()
    lang = {
        "1": {"name":"English",  "code":"en",      "voice":"en-IN-NeerjaNeural"},
        "2": {"name":"Hindi",    "code":"hi",       "voice":"hi-IN-SwaraNeural"},
        "3": {"name":"Hinglish", "code":"hinglish", "voice":"hi-IN-MadhurNeural"},
    }.get(lc, {"name":"English","code":"en","voice":"en-IN-NeerjaNeural"})
    print(f"✅ {lang['name']}")

    print("\n⏱️ Mode:")
    print("  1. Brief    (5-6 slides, ~1 min)")
    print("  2. Detailed (11-12 slides, ~3 min + web info)")
    mc = input("Choice (1/2): ").strip()
    mode = {
        "1": {"name":"Brief",    "slides":5,  "words":130, "detailed":False},
        "2": {"name":"Detailed", "slides":11, "words":400, "detailed":True},
    }.get(mc, {"name":"Brief","slides":5,"words":130,"detailed":False})
    print(f"✅ {mode['name']} — {mode['slides']} slides")

    return lang, mode


# ==================== STEP 3: WEB FETCH ====================

def fetch_web_info(summary):
    print(f"\n{'='*70}")
    print("STEP 3: WEB INFO (TAVILY)")
    print('='*70)
    try:
        from tavily import TavilyClient
        groq = Groq(api_key=GROQ_API_KEY)
        r = groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user",
                       "content":f"4-5 word topic only, nothing else:\n{summary[:300]}"}],
            max_tokens=12
        )
        topic = r.choices[0].message.content.strip()
        print(f"🔍 Topic: {topic}")
        tv  = TavilyClient(api_key=TAVILY_API_KEY)
        res = tv.search(query=topic, max_results=3, search_depth="basic")
        web = " ".join(x['content'][:300] for x in res['results'])
        print("✅ Web info fetched!")
        return web
    except Exception as e:
        print(f"⚠️ Skipping web: {e}")
        return ""


# ==================== STEP 4: GROQ SLIDE CONTENT ====================

def generate_slide_content(summary, transcript, web_info, mode):
    print(f"\n{'='*70}")
    print("STEP 4: GROQ — GENERATING SLIDE CONTENT")
    print('='*70)

    n   = mode['slides']
    web = f"\nWEB INFO:\n{web_info}" if web_info else ""

    prompt = f"""
You are creating {n} professional presentation slides.

SUMMARY:
{summary}

TRANSCRIPT:
{transcript[:800]}
{web}

Generate EXACTLY {n} slides as a JSON array.

Slide types:
- "title"      : slide 1 only       — fields: title, subtitle, emoji (1 relevant emoji)
- "bullets"    : key points slide   — fields: title, emoji, points[] (max 4, each max 12 words)
- "numbered"   : steps/process      — fields: title, emoji, points[] (max 4, each max 12 words)
- "two_column" : compare/contrast   — fields: title, emoji, left_header, right_header, left_points[], right_points[]
- "stat"       : highlight numbers  — fields: title, emoji, stats[] (each: {{value, label}}, max 3)
- "conclusion" : last slide only    — fields: title, emoji, points[] (max 3 takeaways)

RULES:
- Slide 1: always type=title
- Slide {n}: always type=conclusion
- Use variety — mix bullet, numbered, two_column, stat types
- Each point max 12 words
- Pick a relevant emoji per slide
- Only relevant content from transcript, no filler

Return ONLY valid JSON array, no markdown fences:
[{{"slide_num":1,"type":"title","title":"...","subtitle":"...","emoji":"🚀"}}, ...]
"""

    groq = Groq(api_key=GROQ_API_KEY)
    r = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        max_tokens=2500
    )
    raw = r.choices[0].message.content.strip()
    raw = re.sub(r"^```[a-z]*\n?","",raw)
    raw = re.sub(r"\n?```$","",raw).strip()

    try:
        slides = json.loads(raw)
        print(f"✅ {len(slides)} slides generated!")
        return slides
    except Exception as e:
        print(f"❌ JSON parse error: {e}\nRaw: {raw[:300]}")
        return None


# ==================== STEP 5: HTML → SCREENSHOT ====================

def slide_to_html(s, slide_num, total):
    """Generate beautiful HTML for each slide type"""

    stype   = s.get("type","bullets")
    title   = s.get("title","")
    emoji   = s.get("emoji","📌")
    num_str = f"{slide_num:02d} / {total:02d}"

    # ── Common CSS ──────────────────────────────────────────────────
    base_css = """
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
        width:1280px; height:720px; overflow:hidden;
        font-family: 'Segoe UI', Arial, sans-serif;
        background: #F5F4F0;
    }
    .slide { width:1280px; height:720px; position:relative; overflow:hidden; }

    /* dot grid */
    .slide::before {
        content:'';
        position:absolute; inset:0;
        background-image: radial-gradient(circle, #C8C6C0 1px, transparent 1px);
        background-size: 38px 38px;
        opacity:0.5; z-index:0;
    }

    .header {
        position:relative; z-index:2;
        background:#12203E;
        padding:0 32px;
        height:76px;
        display:flex; align-items:center; justify-content:space-between;
        border-left:6px solid #00B4C8;
    }
    .header-title {
        font-size:28px; font-weight:700;
        color:#FFFFFF; letter-spacing:0.3px;
    }
    .header-right {
        display:flex; align-items:center; gap:16px;
    }
    .slide-emoji { font-size:28px; }
    .slide-num {
        font-size:13px; color:#8BA0C8;
        font-weight:500; letter-spacing:1px;
    }
    .content { position:relative; z-index:2; padding:24px 36px; }

    /* Cards */
    .card {
        background:#FFFFFF;
        border-radius:12px;
        border:1px solid #DCE8EC;
        padding:16px 20px;
        margin-bottom:14px;
        display:flex; align-items:center; gap:14px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        transition: all 0.2s;
    }
    .bullet-dot {
        width:14px; height:14px; border-radius:50%;
        background:#00B4C8; flex-shrink:0;
    }
    .num-badge {
        width:36px; height:36px; border-radius:50%;
        background:#12203E; color:#fff;
        font-size:16px; font-weight:700;
        display:flex; align-items:center; justify-content:center;
        flex-shrink:0;
    }
    .card-text {
        font-size:17px; color:#12203E;
        font-weight:500; line-height:1.4;
    }

    /* Bottom bar */
    .bottom-bar {
        position:absolute; bottom:0; left:0; right:0;
        height:34px; background:#12203E; z-index:2;
        display:flex; align-items:center; padding:0 20px;
        border-top:3px solid #00B4C8;
    }
    .bottom-label {
        font-size:11px; color:#5A7099; letter-spacing:1.5px;
        text-transform:uppercase; font-weight:600;
    }
    """

    # ── TITLE SLIDE ─────────────────────────────────────────────────
    if stype == "title":
        subtitle = s.get("subtitle","")
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
{base_css}
.title-slide {{
    width:1280px; height:720px;
    background: linear-gradient(135deg, #0A1628 0%, #12203E 50%, #0D2847 100%);
    display:flex; flex-direction:column;
    justify-content:center; align-items:center;
    position:relative; overflow:hidden;
}}
.title-slide::before {{
    content:'';
    position:absolute; inset:0;
    background-image: radial-gradient(circle, rgba(0,180,200,0.15) 1px, transparent 1px);
    background-size:40px 40px;
}}
.top-bar {{
    position:absolute; top:0; left:0; right:0;
    height:5px; background:linear-gradient(90deg,#00B4C8,#6C3CB4);
}}
.title-emoji {{
    font-size:72px; margin-bottom:24px; z-index:2;
    filter: drop-shadow(0 4px 12px rgba(0,180,200,0.4));
}}
.main-title {{
    font-size:52px; font-weight:800;
    color:#FFFFFF; text-align:center;
    z-index:2; line-height:1.2;
    max-width:900px;
    text-shadow: 0 2px 20px rgba(0,180,200,0.3);
}}
.cyan-line {{
    width:120px; height:4px;
    background:linear-gradient(90deg,#00B4C8,#6C3CB4);
    border-radius:2px; margin:20px auto;
    z-index:2;
}}
.subtitle {{
    font-size:20px; color:#8BA8C8;
    text-align:center; z-index:2;
    max-width:700px; line-height:1.5;
}}
.corner-mark {{
    position:absolute; width:30px; height:30px;
    border-color:#1E3A5F; border-style:solid;
    opacity:0.6;
}}
.tl {{ top:20px; left:20px; border-width:2px 0 0 2px; }}
.tr {{ top:20px; right:20px; border-width:2px 2px 0 0; }}
.bl {{ bottom:20px; left:20px; border-width:0 0 2px 2px; }}
.br {{ bottom:20px; right:20px; border-width:0 2px 2px 0; }}
</style></head><body>
<div class="title-slide">
    <div class="top-bar"></div>
    <div class="corner-mark tl"></div>
    <div class="corner-mark tr"></div>
    <div class="corner-mark bl"></div>
    <div class="corner-mark br"></div>
    <div class="title-emoji">{emoji}</div>
    <div class="main-title">{title}</div>
    <div class="cyan-line"></div>
    <div class="subtitle">{subtitle}</div>
</div>
</body></html>"""

    # ── BULLETS SLIDE ───────────────────────────────────────────────
    elif stype == "bullets":
        points = s.get("points",[])
        cards  = ""
        for pt in points[:4]:
            cards += f"""
            <div class="card">
                <div class="bullet-dot"></div>
                <div class="card-text">{pt}</div>
            </div>"""
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>{base_css}</style></head><body>
<div class="slide">
    <div class="header">
        <div class="header-title">{title}</div>
        <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
        </div>
    </div>
    <div class="content">{cards}</div>
    <div class="bottom-bar">
        <span class="bottom-label">AI VIDEO OVERVIEW</span>
    </div>
</div></body></html>"""

    # ── NUMBERED SLIDE ──────────────────────────────────────────────
    elif stype == "numbered":
        points = s.get("points",[])
        cards  = ""
        for i,pt in enumerate(points[:4],1):
            cards += f"""
            <div class="card">
                <div class="num-badge">{i}</div>
                <div class="card-text">{pt}</div>
            </div>"""
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>{base_css}</style></head><body>
<div class="slide">
    <div class="header">
        <div class="header-title">{title}</div>
        <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
        </div>
    </div>
    <div class="content">{cards}</div>
    <div class="bottom-bar">
        <span class="bottom-label">AI VIDEO OVERVIEW</span>
    </div>
</div></body></html>"""

    # ── TWO COLUMN SLIDE ────────────────────────────────────────────
    elif stype == "two_column":
        lh  = s.get("left_header","Left")
        rh  = s.get("right_header","Right")
        lps = s.get("left_points",[])
        rps = s.get("right_points",[])

        def col_cards(pts, accent):
            out = ""
            for pt in pts[:3]:
                out += f"""
                <div style="background:#fff;border-radius:10px;
                    border:1px solid #DCE8EC;padding:14px 16px;
                    margin-bottom:12px;
                    border-left:4px solid {accent};
                    font-size:15px;color:#12203E;font-weight:500;
                    line-height:1.4;
                    box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                    {pt}
                </div>"""
            return out

        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
{base_css}
.two-col {{
    display:grid; grid-template-columns:1fr 1fr;
    gap:20px; padding:20px 32px;
    position:relative; z-index:2;
}}
.col-header {{
    border-radius:10px; padding:12px 20px;
    font-size:17px; font-weight:700;
    color:#fff; text-align:center;
    margin-bottom:14px;
}}
.col-left  .col-header {{ background:#00B4C8; }}
.col-right .col-header {{ background:#12203E; }}
</style></head><body>
<div class="slide">
    <div class="header">
        <div class="header-title">{title}</div>
        <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
        </div>
    </div>
    <div class="two-col">
        <div class="col-left">
            <div class="col-header">{lh}</div>
            {col_cards(lps,"#00B4C8")}
        </div>
        <div class="col-right">
            <div class="col-header">{rh}</div>
            {col_cards(rps,"#6C3CB4")}
        </div>
    </div>
    <div class="bottom-bar">
        <span class="bottom-label">AI VIDEO OVERVIEW</span>
    </div>
</div></body></html>"""

    # ── STAT SLIDE ──────────────────────────────────────────────────
    elif stype == "stat":
        stats = s.get("stats",[])
        stat_cards = ""
        colors = ["#00B4C8","#6C3CB4","#12203E"]
        for i,st in enumerate(stats[:3]):
            c = colors[i % len(colors)]
            stat_cards += f"""
            <div style="background:#fff;border-radius:16px;
                border:1px solid #DCE8EC;padding:30px 20px;
                text-align:center;
                box-shadow:0 4px 16px rgba(0,0,0,0.06);">
                <div style="font-size:54px;font-weight:800;color:{c};
                    line-height:1;">{st.get('value','')}</div>
                <div style="font-size:15px;color:#5A6A7A;
                    margin-top:10px;font-weight:500;">{st.get('label','')}</div>
            </div>"""

        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
{base_css}
.stat-grid {{
    display:grid;
    grid-template-columns: repeat({min(len(stats),3)}, 1fr);
    gap:24px; padding:30px 40px;
    position:relative; z-index:2;
}}
</style></head><body>
<div class="slide">
    <div class="header">
        <div class="header-title">{title}</div>
        <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
        </div>
    </div>
    <div class="stat-grid">{stat_cards}</div>
    <div class="bottom-bar">
        <span class="bottom-label">AI VIDEO OVERVIEW</span>
    </div>
</div></body></html>"""

    # ── CONCLUSION SLIDE ────────────────────────────────────────────
    else:
        points = s.get("points",[])
        n_cols = min(len(points),3)
        takeaway_cards = ""
        grad_colors = [
            ("linear-gradient(135deg,#00B4C8,#0090A0)","#fff"),
            ("linear-gradient(135deg,#12203E,#1E3A6E)","#fff"),
            ("linear-gradient(135deg,#6C3CB4,#8B50D4)","#fff"),
        ]
        for i,pt in enumerate(points[:3]):
            bg,tc = grad_colors[i % len(grad_colors)]
            takeaway_cards += f"""
            <div style="background:{bg};border-radius:16px;
                padding:28px 22px;text-align:center;
                box-shadow:0 4px 20px rgba(0,0,0,0.12);">
                <div style="font-size:32px;margin-bottom:14px;">{["✅","💡","🎯"][i]}</div>
                <div style="font-size:15px;color:{tc};
                    font-weight:500;line-height:1.5;">{pt}</div>
            </div>"""

        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
{base_css}
.conclusion-header {{
    background:#12203E; padding:0 32px;
    height:76px; display:flex;
    align-items:center; justify-content:space-between;
    border-left:6px solid #6C3CB4;
    position:relative; z-index:2;
}}
.conclusion-tag {{
    font-size:12px;color:#9B7ED4;
    letter-spacing:2px;font-weight:700;
    text-transform:uppercase;
}}
.takeaway-grid {{
    display:grid;
    grid-template-columns: repeat({n_cols},1fr);
    gap:22px; padding:28px 36px;
    position:relative; z-index:2;
}}
</style></head><body>
<div class="slide">
    <div class="conclusion-header">
        <div>
            <div class="conclusion-tag">✦ KEY TAKEAWAY</div>
            <div style="font-size:26px;font-weight:700;color:#fff;margin-top:4px;">{title}</div>
        </div>
        <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
        </div>
    </div>
    <div class="takeaway-grid">{takeaway_cards}</div>
    <div class="bottom-bar">
        <span class="bottom-label">AI VIDEO OVERVIEW</span>
    </div>
</div></body></html>"""


def screenshot_slides(slides):
    """Playwright se HTML → PNG screenshot"""
    print(f"\n{'='*70}")
    print("STEP 5: HTML → SCREENSHOT (PLAYWRIGHT)")
    print('='*70)

    from playwright.sync_api import sync_playwright

    out_dir = Path("output/slides_img")
    out_dir.mkdir(parents=True, exist_ok=True)

    total  = len(slides)
    paths  = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page    = browser.new_page(viewport={"width":W,"height":H})

        for s in slides:
            html = slide_to_html(s, s['slide_num'], total)

            # Save HTML temp
            tmp = str(out_dir / f"tmp_{s['slide_num']}.html")
            with open(tmp,"w",encoding="utf-8") as f:
                f.write(html)

            page.goto(f"file:///{os.path.abspath(tmp)}")
            page.wait_for_timeout(400)  # fonts/emoji load

            img_path = str(out_dir / f"slide_{s['slide_num']:02d}.png")
            page.screenshot(path=img_path, clip={"x":0,"y":0,"width":W,"height":H})

            print(f"  ✅ Slide {s['slide_num']}: {s.get('title','')[:50]}")
            paths.append(img_path)

            os.remove(tmp)  # cleanup

        browser.close()

    return paths


# ==================== STEP 6: AUDIO ====================

def generate_audio(summary, transcript, web_info, lang, mode, slides):
    print(f"\n{'='*70}")
    print("STEP 6: AUDIO SCRIPT + TTS")
    print('='*70)

    groq = Groq(api_key=GROQ_API_KEY)

    lang_inst = {
        "en":       "Write ONLY in English. Clear, engaging narrator voice.",
        "hi":       "Write ONLY in Hindi (Devanagari script). Natural Hindi.",
        "hinglish": "Hinglish mein likho — Hindi+English mix, jaise koi dost explain kar raha ho.",
    }

    slide_titles = "\n".join(
        f"Slide {s['slide_num']}: {s.get('title','')}" for s in slides
    )
    web = f"\nWEB INFO:\n{web_info}" if web_info else ""

    prompt = f"""
Create a continuous audio narration for this video presentation.

SLIDES:
{slide_titles}

SUMMARY:
{summary}

TRANSCRIPT:
{transcript[:600]}
{web}

INSTRUCTIONS:
- {lang_inst[lang['code']]}
- Exactly {mode['words']} words
- One smooth flowing script matching the slide order
- NO "Hello", NO "Welcome", NO "In this video"
- Start directly with the main topic
- Student-friendly, no irrelevant info
- Natural pauses between slide topics

Write ONLY the narration script, nothing else.
"""

    r = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        max_tokens=700
    )
    script = r.choices[0].message.content.strip()
    print(f"✅ Script: {len(script.split())} words")

    with open("output/video_script.txt","w",encoding="utf-8") as f:
        f.write(script)

    audio_path = "output/video_audio.mp3"

    async def tts():
        c = edge_tts.Communicate(script, lang['voice'])
        await c.save(audio_path)

    asyncio.run(tts())
    print(f"✅ Audio: {audio_path}")
    return audio_path


# ==================== STEP 7: CREATE VIDEO ====================

def create_video(image_paths, audio_path):
    print(f"\n{'='*70}")
    print("STEP 7: CREATING VIDEO")
    print('='*70)

    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

    audio     = AudioFileClip(audio_path)
    total_dur = audio.duration
    per_slide = total_dur / len(image_paths)

    print(f"📊 Audio: {total_dur:.1f}s | Per slide: {per_slide:.1f}s")

    clips = []
    for i,p in enumerate(image_paths):
        clip = ImageClip(p).set_duration(per_slide)
        clips.append(clip)
        print(f"  🎞️ Slide {i+1} added")

    final = concatenate_videoclips(clips, method="compose")
    final_audio = audio.subclip(0, final.duration)
    final = final.set_audio(audio)

    out = "output/video_overview.mp4"
    print("\n⏳ Exporting...")
    final.write_videofile(
        out,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        audio=True,
        temp_audiofile="temp_audio.m4a",
        remove_temp=True,
        logger=None
    )
    print(f"✅ Video: {out}")
    return out


# ==================== MAIN ====================

if __name__ == "__main__":

    summary, transcript = load_files()
    if not summary: exit()

    lang, mode = get_user_options()

    web_info = fetch_web_info(summary) if mode['detailed'] else ""

    slides = generate_slide_content(summary, transcript, web_info, mode)
    if not slides: exit()

    image_paths = screenshot_slides(slides)

    audio_path = generate_audio(
        summary, transcript, web_info, lang, mode, slides
    )

    video_path = create_video(image_paths, audio_path)

    print(f"\n{'='*70}")
    print("✨ VIDEO OVERVIEW COMPLETE!")
    print('='*70)
    print(f"\n📂 Output:")
    print(f"   ├── output/slides_img/      (slide PNGs)")
    print(f"   ├── output/video_script.txt")
    print(f"   ├── output/video_audio.mp3  (standalone)")
    print(f"   └── output/video_overview.mp4  ← PLAY THIS 🎬")