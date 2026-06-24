# backend/app.py - SnapSummary Flask Backend

import os
import re
import json
import time
import asyncio
import traceback
import warnings
import subprocess
import sys
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv


load_dotenv()
warnings.filterwarnings('ignore')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

app = Flask(__name__)
CORS(app)

Path("output").mkdir(exist_ok=True)
Path("downloads").mkdir(exist_ok=True)
Path("frames").mkdir(exist_ok=True)
Path("output/slides_img").mkdir(parents=True, exist_ok=True)


# ==================== HELPERS ====================

def get_api_key(data):
    if not data:
        return GROQ_API_KEY
    key = data.get('groq_key')
    if key and isinstance(key, str) and key.strip().startswith('gsk_'):
        return key.strip()
    return GROQ_API_KEY

def get_voice(lang):
    return {
        "en":       "en-IN-NeerjaNeural",
        "hi":       "hi-IN-SwaraNeural",
        "hinglish": "hi-IN-MadhurNeural",
    }.get(lang, "en-IN-NeerjaNeural")

def get_words(mode):
    return 130 if mode == "brief" else 400

def get_slides(mode):
    return 5 if mode == "brief" else 11

def _save_transcript(url, title, transcript, lang, mode, visual_context=None):
    with open("output/latest_transcript.txt", "w", encoding="utf-8") as f:
        f.write(transcript or "")
    with open("output/latest_meta.json", "w", encoding="utf-8") as f:
        json.dump({
            "url": url, "title": title,
            "lang": lang, "mode": mode,
            "has_audio": bool(transcript and len(transcript) > 10),
            "visual_context": visual_context or ""
        }, f)


def has_audio(video_path):
    """Check if video has audio stream"""
    import subprocess, json
    result = subprocess.run([
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams', video_path
    ], capture_output=True, text=True)
    try:
        data    = json.loads(result.stdout)
        streams = data.get('streams', [])
        return any(s.get('codec_type') == 'audio' for s in streams)
    except:
        return False


def extract_key_frames(video_path, max_frames=10):
    """Extract key frames using adaptive interval"""
    import cv2
    from pathlib import Path

    out_dir = Path("output/vision_frames")
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.jpg"):
        f.unlink()

    cap      = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("⚠️ Video capture failed to open")
        return []
    
    fps      = cap.get(cv2.CAP_PROP_FPS) or 25
    total_f  = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if total_f <= 0:
        print("⚠️ No frames in video")
        cap.release()
        return []
        
    duration = total_f / fps

    # Determine adaptive interval in seconds
    if duration < 30:
        interval_sec = 5
    elif duration <= 120:
        interval_sec = 15
    else:
        interval_sec = 30

    sample_every = max(1, int(fps * interval_sec))

    # If this would result in more than max_frames, adjust sample_every to hit max_frames exactly
    projected_frames = total_f / sample_every
    if projected_frames > max_frames:
        sample_every = max(1, int(total_f / max_frames))

    saved, frame_idx, prev_gray = [], 0, None

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        # Cap at max_frames
        if len(saved) >= max_frames:
            break
        if frame_idx % sample_every == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is None or cv2.absdiff(gray, prev_gray).mean() > 10:
                path = str(out_dir / f"frame_{frame_idx:05d}.jpg")
                cv2.imwrite(path, frame)
                saved.append(path)
            prev_gray = gray
        frame_idx += 1

    cap.release()
    print(f"✅ {len(saved)} frames extracted")
    return saved


def analyze_frames_with_vision(frame_paths, api_key=None):
    """Analyze frames using Groq Vision - works for diagrams, charts, text slides"""
    import base64
    from groq import Groq

    key = api_key or GROQ_API_KEY
    if not key:
        print("⚠️ No Groq API Key found for vision analysis")
        return ""

    client       = Groq(api_key=key)
    descriptions = []
    total        = len(frame_paths)

    for i, path in enumerate(frame_paths):
        print(f"  👁️ Analyzing frame {i+1}/{total}...")
        try:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            response = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": { "url": f"data:image/jpeg;base64,{image_data}" }
                        },
                        {
                            "type": "text",
                            "text": "Describe all visible content in this frame — any text, diagrams, charts, code, slides, or visual elements. Be specific and extract all readable text. If it is a diagram explain its structure and meaning."
                        }
                    ]
                }],
                max_tokens=400
            )
            desc = response.choices[0].message.content.strip()
            descriptions.append(f"Frame {i+1}: {desc}")
            print(f"    ✅ {desc[:80]}...")
        except Exception as e:
            print(f"    ⚠️ Frame {i+1} failed: {e}")

    combined = "\n\n".join(descriptions)
    print(f"✅ Visual analysis complete ({len(descriptions)} frames)")
    return combined



# ==================== STEP 1: DOWNLOAD ====================

def download_video(url):
    from yt_dlp import YoutubeDL
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        return path, info.get('title', 'video'), info.get('duration', 0)


# ==================== STEP 2: TRANSCRIBE ====================

def transcribe(video_path, api_key=None):
    from groq import Groq

    audio_path = video_path.rsplit('.', 1)[0] + '_temp.mp3'
    subprocess.run([
        'ffmpeg', '-i', video_path,
        '-ar', '16000', '-ac', '1', '-b:a', '32k',
        audio_path, '-y'
    ], capture_output=True)

    if not os.path.exists(audio_path):
        raise Exception("Audio extraction failed")

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"📊 Audio: {size_mb:.1f} MB")

    try:
        client = Groq(api_key=api_key or GROQ_API_KEY)
        print("⚡ Groq Whisper large-v3...")

        if size_mb > 24:
            # Chunked transcription
            full_text = ""
            chunk_dir = "downloads/chunks"
            Path(chunk_dir).mkdir(parents=True, exist_ok=True)

            subprocess.run([
                'ffmpeg', '-i', audio_path,
                '-f', 'segment', '-segment_time', '300',
                '-c', 'copy', f'{chunk_dir}/chunk_%03d.mp3', '-y'
            ], capture_output=True)

            chunks = sorted(Path(chunk_dir).glob("chunk_*.mp3"))
            for i, chunk in enumerate(chunks):
                print(f"  ⚡ Chunk {i+1}/{len(chunks)}...")
                with open(chunk, 'rb') as f:
                    result = client.audio.transcriptions.create(
                        file=(chunk.name, f.read()),
                        model="whisper-large-v3",
                        response_format="text",
                    )
                full_text += result + " "
                chunk.unlink()

            os.remove(audio_path)
            return full_text.strip(), "auto"

        with open(audio_path, 'rb') as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model="whisper-large-v3",
                response_format="text",
            )

        os.remove(audio_path)
        print(f"✅ Transcription done! ({len(transcription)} chars)")
        return transcription, "auto"

    except Exception as e:
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise Exception(f"Transcription failed: {e}")


# ==================== STEP 3: SUMMARY ====================

def groq_summary(transcript, lang, mode, api_key=None, visual_context=None):
    from groq import Groq

    lang_inst = {
        "en":       "Respond in English only.",
        "hi":       "Respond in Hindi (Devanagari) only.",
        "hinglish": "Respond in Hinglish (Hindi+English mix).",
    }.get(lang, "Respond in English only.")

    if mode == "brief":
        para_sentences = 4
        points_count   = 4
        detail_inst    = "Keep it concise."
    else:
        para_sentences = 7
        points_count   = 8
        detail_inst    = "Be detailed with examples and explanations."

    visual_section = f"""
VISUAL CONTENT (from video frames analysis):
{visual_context}
""" if visual_context else ""

    prompt = f"""
You are an expert summarizer. Summarize this video content. {lang_inst}

AUDIO TRANSCRIPT:
{transcript if transcript and len(transcript) > 10 else "No audio/voice in this video."}

{visual_section}

INSTRUCTIONS:
- If no audio transcript, base summary entirely on visual content
- If both exist, combine audio and visual for a complete summary
- Write ABSTRACTIVE summary in THIRD PERSON
- NEVER copy sentences — rephrase EVERYTHING
- {detail_inst}

Return ONLY valid JSON:
{{
  "paragraph": "Abstractive paragraph of {para_sentences} sentences",
  "points": ["point 1", "point 2"...],
  "takeaway": "One powerful takeaway"
}}

RULES:
- Exactly {points_count} bullet points, max 15 words each
- Third person only
- No filler
"""
    client = Groq(api_key=api_key or GROQ_API_KEY)
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000
    )
    raw = r.choices[0].message.content.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        print(f"Raw Output:\n{raw}\n{'-'*50}")
        raise e


# ==================== AUDIO ====================

def generate_audio_script(transcript, summary_data, lang, mode, api_key=None, visual_context=None):
    from groq import Groq

    lang_inst = {
        "en":       "Write ONLY in English.",
        "hi":       "Write ONLY in Hindi (Devanagari).",
        "hinglish": "Write in Hinglish — Hindi+English mix.",
    }.get(lang, "Write ONLY in English.")

    points = "\n".join(summary_data.get("points", []))
    words  = get_words(mode)

    visual_section = f"\nVISUAL CONTENT (from video frames analysis):\n{visual_context}" if visual_context else ""

    prompt = f"""
Create audio narration script.

PARAGRAPH:
{summary_data.get('paragraph','')}

KEY POINTS:
{points}

AUDIO TRANSCRIPT:
{transcript if transcript and len(transcript) > 10 else "No audio/voice in this video."}
{visual_section}

INSTRUCTIONS:
- {lang_inst}
- Exactly {words} words
- No "Hello", no "Welcome", start directly
- Smooth, engaging, student-friendly
- No irrelevant info

Write ONLY the script.
"""
    client = Groq(api_key=api_key or GROQ_API_KEY)
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600
    )
    return r.choices[0].message.content.strip()


def generate_tts(script, voice, out_path):
    tts_script = f"""
import asyncio, edge_tts
async def run():
    c = edge_tts.Communicate({repr(script)}, {repr(voice)})
    await c.save({repr(out_path)})
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", tts_script],
        capture_output=True, timeout=120
    )
    if result.returncode != 0:
        raise Exception(f"TTS failed: {result.stderr.decode()}")
    return out_path


# ==================== SLIDES ====================

def generate_slides(transcript, summary_data, lang, mode, api_key=None, visual_context=None):
    from groq import Groq
    n        = get_slides(mode)
    para     = summary_data.get("paragraph", "")
    points   = summary_data.get("points", [])
    takeaway = summary_data.get("takeaway", "")

    visual_section = f"\nVISUAL CONTENT (from video frames analysis):\n{visual_context}" if visual_context else ""

    prompt = f"""
Create {n} presentation slides as JSON array.

PARAGRAPH: {para}
KEY POINTS: {chr(10).join(points)}
TAKEAWAY: {takeaway}
AUDIO TRANSCRIPT: {transcript[:800] if transcript else "No audio/voice in this video."}
{visual_section}

Slide types:
- "title"      : slide 1 — title, subtitle, emoji
- "summary"    : slide 2 ALWAYS — title, emoji, paragraph (2-3 abstractive sentences)
- "bullets"    : title, emoji, points[] (max 4, each 15-20 words detailed)
- "numbered"   : title, emoji, points[] (max 4, each 15-20 words)
- "two_column" : title, emoji, left_header, right_header, left_points[], right_points[]
- "conclusion" : last slide — title, emoji, points[] (max 3, each 20-25 words)

RULES:
- Slide 1: title, Slide 2: summary, Slide {n}: conclusion
- Points must be DETAILED full sentences not short phrases
- Abstractive content — rephrase, never copy transcript
- English only
- Return ONLY valid JSON array

[{{"slide_num":1,"type":"title","title":"...","subtitle":"...","emoji":"..."}}]
"""
    client = Groq(api_key=api_key or GROQ_API_KEY)
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000
    )
    raw = r.choices[0].message.content.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw).strip()
    return json.loads(raw)

def slide_to_html(s, slide_num, total):
    stype   = s.get("type", "bullets")
    title   = s.get("title", "")
    emoji   = s.get("emoji", "📌")
    num_str = f"{slide_num:02d} / {total:02d}"

    base_css = """
    * { margin:0; padding:0; box-sizing:border-box; }
    body { width:1280px; height:720px; overflow:hidden; font-family:'Segoe UI',Arial,sans-serif; background:#F5F4F0; }
    .slide { width:1280px; height:720px; position:relative; overflow:hidden; }
    .slide::before { content:''; position:absolute; inset:0; background-image:radial-gradient(circle,#C8C6C0 1px,transparent 1px); background-size:38px 38px; opacity:0.5; z-index:0; }
    .header { position:relative; z-index:2; background:#12203E; padding:0 32px; height:76px; display:flex; align-items:center; justify-content:space-between; border-left:6px solid #00B4C8; }
    .header-title { font-size:28px; font-weight:700; color:#FFFFFF; }
    .header-right { display:flex; align-items:center; gap:16px; }
    .slide-emoji { font-size:28px; }
    .slide-num { font-size:13px; color:#8BA0C8; font-weight:500; letter-spacing:1px; }
    .content { position:relative; z-index:2; padding:24px 36px; }
    .card { background:#FFFFFF; border-radius:12px; border:1px solid #DCE8EC; padding:16px 20px; margin-bottom:14px; display:flex; align-items:center; gap:14px; box-shadow:0 2px 8px rgba(0,0,0,0.04); }
    .bullet-dot { width:14px; height:14px; border-radius:50%; background:#00B4C8; flex-shrink:0; }
    .num-badge { width:36px; height:36px; border-radius:50%; background:#12203E; color:#fff; font-size:16px; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
    .card-text { font-size:17px; color:#12203E; font-weight:500; line-height:1.4; }
    .bottom-bar { position:absolute; bottom:0; left:0; right:0; height:34px; background:#12203E; z-index:2; display:flex; align-items:center; padding:0 20px; border-top:3px solid #00B4C8; }
    .bottom-label { font-size:11px; color:#5A7099; letter-spacing:1.5px; text-transform:uppercase; font-weight:600; }
    """

    if stype == "title":
        subtitle = s.get("subtitle", "")
        
        # Topic se image fetch karo
        bg_style = "background:linear-gradient(135deg,#0A1628 0%,#12203E 50%,#0D2847 100%);"
        
        if UNSPLASH_ACCESS_KEY:
            topic = title[:30]
            bg_img = get_unsplash_image(topic)
            if bg_img:
                # Absolute path Windows style
                abs_path = os.path.abspath(bg_img).replace('\\','/')
                bg_style = f"background: linear-gradient(rgba(10,22,40,0.75), rgba(10,22,40,0.85)), url('file:///{abs_path}') center/cover no-repeat;"
        
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ width:1280px; height:720px; overflow:hidden; font-family:'Segoe UI',Arial,sans-serif; }}
        .ts {{ width:1280px; height:720px; {bg_style} display:flex; flex-direction:column; justify-content:center; align-items:center; position:relative; overflow:hidden; }}
        .ts::before {{ content:''; position:absolute; inset:0; background-image:radial-gradient(circle,rgba(0,180,200,0.1) 1px,transparent 1px); background-size:40px 40px; }}
        .top-bar {{ position:absolute; top:0; left:0; right:0; height:5px; background:linear-gradient(90deg,#00B4C8,#6C3CB4); }}
        .emoji {{ font-size:72px; margin-bottom:24px; z-index:2; }}
        .main {{ font-size:52px; font-weight:800; color:#FFFFFF; text-align:center; z-index:2; line-height:1.2; max-width:900px; text-shadow:0 2px 20px rgba(0,0,0,0.5); }}
        .line {{ width:120px; height:4px; background:linear-gradient(90deg,#00B4C8,#6C3CB4); border-radius:2px; margin:20px auto; z-index:2; }}
        .sub {{ font-size:20px; color:#CBD5E1; text-align:center; z-index:2; max-width:700px; line-height:1.5; text-shadow:0 1px 8px rgba(0,0,0,0.5); }}
        </style></head><body>
        <div class="ts">
        <div class="top-bar"></div>
        <div class="emoji">{emoji}</div>
        <div class="main">{title}</div>
        <div class="line"></div>
        <div class="sub">{subtitle}</div>
        </div></body></html>"""
    elif stype == "summary":
        paragraph = s.get("paragraph", "")
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
        {base_css}
        .para-box {{
            background:#FFFFFF;
            border-radius:16px;
            border:1px solid #DCE8EC;
            border-left:6px solid #00B4C8;
            padding:32px 40px;
            margin:24px 36px;
            position:relative;
            z-index:2;
            box-shadow:0 4px 20px rgba(0,0,0,0.06);
        }}
        .para-text {{
            font-size:19px;
            color:#12203E;
            line-height:1.9;
            font-weight:400;
        }}
        .quote-mark {{
            font-size:72px;
            color:#00B4C8;
            opacity:0.2;
            position:absolute;
            top:10px;
            left:20px;
            line-height:1;
            font-family:Georgia,serif;
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
        <div class="para-box">
            <div class="quote-mark">"</div>
            <div class="para-text">{paragraph}</div>
        </div>
        <div class="bottom-bar">
            <span class="bottom-label">SnapSummary AI</span>
        </div>
        </div></body></html>"""

    elif stype == "bullets":
        points  = s.get("points", [])
        cards   = "".join(f'''
            <div style="background:#FFFFFF;border-radius:12px;border:1px solid #DCE8EC;
                padding:18px 22px;margin-bottom:12px;display:flex;align-items:flex-start;
                gap:14px;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                <div style="width:14px;height:14px;border-radius:50%;background:#00B4C8;
                    flex-shrink:0;margin-top:4px;"></div>
                <div style="font-size:16px;color:#12203E;font-weight:400;line-height:1.6;">{p}</div>
            </div>''' for p in points[:4])
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{base_css}</style></head><body>
        <div class="slide">
        <div class="header">
            <div class="header-title">{title}</div>
            <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
            </div>
        </div>
        <div class="content">{cards}</div>
        <div class="bottom-bar"><span class="bottom-label">SnapSummary AI</span></div>
        </div></body></html>"""

    elif stype == "numbered":
        points = s.get("points", [])
        cards  = "".join(f'''
            <div style="background:#FFFFFF;border-radius:12px;border:1px solid #DCE8EC;
                padding:18px 22px;margin-bottom:12px;display:flex;align-items:flex-start;
                gap:14px;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                <div style="width:36px;height:36px;border-radius:50%;background:#12203E;
                    color:#fff;font-size:16px;font-weight:700;display:flex;
                    align-items:center;justify-content:center;flex-shrink:0;">{i+1}</div>
                <div style="font-size:16px;color:#12203E;font-weight:400;line-height:1.6;">{p}</div>
            </div>''' for i, p in enumerate(points[:4]))
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{base_css}</style></head><body>
        <div class="slide">
        <div class="header">
            <div class="header-title">{title}</div>
            <div class="header-right">
            <span class="slide-emoji">{emoji}</span>
            <span class="slide-num">{num_str}</span>
            </div>
        </div>
        <div class="content">{cards}</div>
        <div class="bottom-bar"><span class="bottom-label">SnapSummary AI</span></div>
        </div></body></html>"""

    elif stype == "two_column":
        lh  = s.get("left_header", "")
        rh  = s.get("right_header", "")
        lps = s.get("left_points", [])
        rps = s.get("right_points", [])
        def col(pts, color):
            return "".join(f'<div style="background:#fff;border-radius:10px;border:1px solid #DCE8EC;padding:14px 16px;margin-bottom:10px;border-left:4px solid {color};font-size:15px;color:#12203E;line-height:1.4;">{p}</div>' for p in pts[:3])
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
        {base_css}
        .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; padding:20px 32px; position:relative; z-index:2; }}
        .col-header {{ border-radius:10px; padding:12px 20px; font-size:17px; font-weight:700; color:#fff; text-align:center; margin-bottom:14px; }}
        </style></head><body>
        <div class="slide">
          <div class="header"><div class="header-title">{title}</div><div class="header-right"><span class="slide-emoji">{emoji}</span><span class="slide-num">{num_str}</span></div></div>
          <div class="two-col">
            <div><div class="col-header" style="background:#00B4C8;">{lh}</div>{col(lps,"#00B4C8")}</div>
            <div><div class="col-header" style="background:#12203E;">{rh}</div>{col(rps,"#6C3CB4")}</div>
          </div>
          <div class="bottom-bar"><span class="bottom-label">SnapSummary AI</span></div>
        </div></body></html>"""

    else:  # conclusion
        points  = s.get("points", [])
        n_cols  = min(len(points), 3)
        grads   = ["linear-gradient(135deg,#00B4C8,#0090A0)", "linear-gradient(135deg,#12203E,#1E3A6E)", "linear-gradient(135deg,#6C3CB4,#8B50D4)"]
        icons   = ["✅", "💡", "🎯"]
        cards   = "".join(f'<div style="background:{grads[i%3]};border-radius:16px;padding:28px 22px;text-align:center;"><div style="font-size:32px;margin-bottom:14px;">{icons[i%3]}</div><div style="font-size:15px;color:#fff;font-weight:500;line-height:1.5;">{p}</div></div>' for i, p in enumerate(points[:3]))
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
        {base_css}
        .conc-header {{ background:#12203E; padding:0 32px; height:76px; display:flex; align-items:center; justify-content:space-between; border-left:6px solid #6C3CB4; position:relative; z-index:2; }}
        .grid {{ display:grid; grid-template-columns:repeat({n_cols},1fr); gap:22px; padding:28px 36px; position:relative; z-index:2; }}
        </style></head><body>
        <div class="slide">
          <div class="conc-header">
            <div><div style="font-size:12px;color:#9B7ED4;letter-spacing:2px;font-weight:700;">✦ KEY TAKEAWAY</div><div style="font-size:26px;font-weight:700;color:#fff;margin-top:4px;">{title}</div></div>
            <div style="display:flex;align-items:center;gap:16px;"><span style="font-size:28px;">{emoji}</span><span style="font-size:13px;color:#8BA0C8;">{num_str}</span></div>
          </div>
          <div class="grid">{cards}</div>
          <div class="bottom-bar"><span class="bottom-label">SnapSummary AI</span></div>
        </div></body></html>"""


def screenshot_slides(slides):
    from playwright.sync_api import sync_playwright

    out_dir = Path("output/slides_img")
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()

    paths = []
    total = len(slides)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        
        # ✅ Single page reuse — faster than creating new page per slide
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        for s in slides:
            html     = slide_to_html(s, s['slide_num'], total)
            tmp      = str(out_dir / f"tmp_{s['slide_num']}.html")
            
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(html)
            
            page.goto(f"file:///{os.path.abspath(tmp)}")
            page.wait_for_timeout(300)  # 500 → 300ms (faster)
            
            img_path = str(out_dir / f"slide_{s['slide_num']:02d}.png")
            page.screenshot(
                path=img_path,
                clip={"x": 0, "y": 0, "width": 1280, "height": 720}
            )
            paths.append(img_path)
            os.remove(tmp)

        browser.close()

    print(f"✅ {len(paths)} slides rendered!")
    return paths
def create_video_with_audio(image_paths, audio_path, out_path):
    try:
        from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

        audio     = AudioFileClip(audio_path)
        total_dur = audio.duration
        per_slide = total_dur / len(image_paths)

        clips = [ImageClip(p).set_duration(per_slide) for p in image_paths]
        video = concatenate_videoclips(clips, method="compose")

        final_audio = audio.subclip(0, video.duration)
        final       = video.set_audio(final_audio)

        final.write_videofile(
            out_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile="temp_audio.m4a",
            remove_temp=True,
            logger=None,
            threads=4,
            preset="ultrafast",
        )
        audio.close()
        print(f"✅ Video created: {out_path}")
        return out_path

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None
    final.write_videofile(
        out_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp_audio.m4a",
        remove_temp=True,
        logger=None,
        threads=4,
        preset="ultrafast",  # ← 40s → ~15s
)

# ==================== ROUTES ====================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "SnapSummary backend running"})


@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.json
    api_key = get_api_key(data)
    url  = data.get('url', '')
    lang = data.get('lang', 'en')
    mode = data.get('mode', 'brief')

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    total_start = time.time()

    try:
        meta_path       = "output/latest_meta.json"
        transcript_path = "output/latest_transcript.txt"
        t1              = time.time()
        visual_context  = None

        if os.path.exists(meta_path) and os.path.exists(transcript_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("url") == url:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    transcript = f.read()
                title          = meta.get("title", "Video")
                visual_context = meta.get("visual_context", "")
                download_time  = 0
                print("✅ Cache hit!")
            else:
                video_path, title, _ = download_video(url)
                
                audio_exists   = has_audio(video_path)
                transcript     = ""
                if audio_exists:
                    print("🎤 Audio detected — transcribing...")
                    transcript, _ = transcribe(video_path, api_key=api_key)
                else:
                    print("🔇 No audio detected — switching to visual mode...")
                
                print("👁️ Extracting and analyzing frames...")
                frames         = extract_key_frames(video_path, max_frames=10)
                visual_context = analyze_frames_with_vision(frames, api_key=api_key)
                
                _save_transcript(url, title, transcript, lang, mode, visual_context)
                download_time  = time.time() - t1
        else:
            video_path, title, _ = download_video(url)
            
            audio_exists   = has_audio(video_path)
            transcript     = ""
            if audio_exists:
                print("🎤 Audio detected — transcribing...")
                transcript, _ = transcribe(video_path, api_key=api_key)
            else:
                print("🔇 No audio detected — switching to visual mode...")
            
            print("👁️ Extracting and analyzing frames...")
            frames         = extract_key_frames(video_path, max_frames=10)
            visual_context = analyze_frames_with_vision(frames, api_key=api_key)
            
            _save_transcript(url, title, transcript, lang, mode, visual_context)
            download_time  = time.time() - t1

        t2      = time.time()
        summary = groq_summary(transcript, lang, mode, api_key=api_key, visual_context=visual_context)
        summary['title'] = title
        summary_time     = time.time() - t2
        total            = time.time() - total_start

        print(f"\n{'='*50}")
        print(f"⏱️  TIME BREAKDOWN")
        print(f"{'='*50}")
        print(f"  📥 Download+Transcribe : {download_time:.1f}s")
        print(f"  📝 Summary             : {summary_time:.1f}s")
        print(f"  ─────────────────────────")
        print(f"  ✅ TOTAL               : {total:.1f}s")
        print(f"{'='*50}\n")

        summary['time_stats'] = {
            "download_transcribe": round(download_time, 1),
            "summary":             round(summary_time, 1),
            "total":               round(total, 1)
        }

        return jsonify(summary)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/audio-overview', methods=['POST'])
def audio_overview():
    data = request.json
    api_key = get_api_key(data)
    url  = data.get('url', '')
    lang = data.get('lang', 'en')
    mode = data.get('mode', 'brief')

    t_start = time.time()

    try:
        visual_context = None
        if os.path.exists("output/latest_transcript.txt") and os.path.exists("output/latest_meta.json"):
            with open("output/latest_transcript.txt", "r", encoding="utf-8") as f:
                transcript = f.read()
            with open("output/latest_meta.json", "r", encoding="utf-8") as f:
                meta = json.load(f)
            title = meta.get("title", "Video")
            visual_context = meta.get("visual_context", "")
            print("✅ Cache hit!")
        else:
            video_path, title, _ = download_video(url)
            
            audio_exists   = has_audio(video_path)
            transcript     = ""
            if audio_exists:
                print("🎤 Audio detected — transcribing...")
                transcript, _ = transcribe(video_path, api_key=api_key)
            else:
                print("🔇 No audio detected — switching to visual mode...")
            
            print("👁️ Extracting and analyzing frames...")
            frames         = extract_key_frames(video_path, max_frames=10)
            visual_context = analyze_frames_with_vision(frames, api_key=api_key)
            
            _save_transcript(url, title, transcript, lang, mode, visual_context)

        summary    = groq_summary(transcript, lang, mode, api_key=api_key, visual_context=visual_context)
        script     = generate_audio_script(transcript, summary, lang, mode, api_key=api_key, visual_context=visual_context)
        voice      = get_voice(lang)
        audio_path = f"output/audio_overview_{lang}_{mode}.mp3"
        generate_tts(script, voice, audio_path)

        total = time.time() - t_start
        print(f"⏱️ Audio overview total: {total:.1f}s")

        return jsonify({
            "success":    True,
            "audio_file": audio_path,
            "script":     script,
            "time":       round(total, 1)
        })

    except Exception as err:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(err)}), 500


@app.route('/video-overview', methods=['POST'])
def video_overview():
    data = request.json
    api_key = get_api_key(data)
    url  = data.get('url', '')
    lang = data.get('lang', 'en')
    mode = data.get('mode', 'brief')

    t_start = time.time()

    try:
        visual_context = None
        if os.path.exists("output/latest_transcript.txt") and os.path.exists("output/latest_meta.json"):
            with open("output/latest_transcript.txt", "r", encoding="utf-8") as f:
                transcript = f.read()
            with open("output/latest_meta.json", "r", encoding="utf-8") as f:
                meta = json.load(f)
            title = meta.get("title", "Video")
            visual_context = meta.get("visual_context", "")
            print("✅ Cache hit!")
        else:
            video_path, title, _ = download_video(url)
            
            audio_exists   = has_audio(video_path)
            transcript     = ""
            if audio_exists:
                print("🎤 Audio detected — transcribing...")
                transcript, _ = transcribe(video_path, api_key=api_key)
            else:
                print("🔇 No audio detected — switching to visual mode...")
            
            print("👁️ Extracting and analyzing frames...")
            frames         = extract_key_frames(video_path, max_frames=10)
            visual_context = analyze_frames_with_vision(frames, api_key=api_key)
            
            _save_transcript(url, title, transcript, lang, mode, visual_context)

        t1      = time.time()
        summary = groq_summary(transcript, lang, mode, api_key=api_key, visual_context=visual_context)
        print(f"⏱️ Summary: {time.time()-t1:.1f}s")

        t2          = time.time()
        slides      = generate_slides(transcript, summary, lang, mode, api_key=api_key, visual_context=visual_context)
        image_paths = screenshot_slides(slides)
        print(f"⏱️ Slides: {time.time()-t2:.1f}s")

        t3         = time.time()
        script     = generate_audio_script(transcript, summary, lang, mode, api_key=api_key, visual_context=visual_context)
        voice      = get_voice(lang)
        audio_path = f"output/video_audio_{lang}_{mode}.mp3"
        generate_tts(script, voice, audio_path)
        print(f"⏱️ Audio: {time.time()-t3:.1f}s")

        t4        = time.time()
        video_out = f"output/video_overview_{lang}_{mode}.mp4"
        create_video_with_audio(image_paths, audio_path, video_out)
        print(f"⏱️ Video render: {time.time()-t4:.1f}s")

        if os.path.exists(audio_path):
            os.remove(audio_path)

        total = time.time() - t_start
        print(f"⏱️ Video overview total: {total:.1f}s")

        return jsonify({
            "success":    True,
            "video_file": video_out,
            "title":      title,
            "time":       round(total, 1)
        })

    except Exception as err:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(err)}), 500


@app.route('/stream', methods=['GET'])
def stream():
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({"error": "No file specified"}), 400
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        print(f"❌ File not found: {abs_path}")
        return jsonify({"error": f"File not found: {abs_path}"}), 404
    print(f"✅ Streaming: {abs_path}")
    return send_file(abs_path)


@app.route('/download', methods=['GET'])
def download():
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({"error": "No file specified"}), 400
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    return send_file(abs_path, as_attachment=True)

def get_unsplash_image(topic, width=1280, height=720):
    """Topic ke liye Unsplash background image fetch karo"""
    try:
        import requests
        url = f"https://api.unsplash.com/photos/random"
        params = {
            "query": topic,
            "orientation": "landscape",
            "client_id": UNSPLASH_ACCESS_KEY
        }
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            img_url = data['urls']['regular']
            # Image download karo
            img_data = requests.get(img_url, timeout=10).content
            img_path = f"output/slides_img/bg_{topic[:20].replace(' ','_')}.jpg"
            with open(img_path, 'wb') as f:
                f.write(img_data)
            print(f"✅ Unsplash image: {topic}")
            return img_path
    except Exception as e:
        print(f"⚠️ Unsplash failed: {e}")
    return None


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 SnapSummary Backend starting...")
    print("="*60)
    print("API: http://localhost:5000")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)