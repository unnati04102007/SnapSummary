# audiotosummary.py - COMPLETE CLEAN VERSION

import os
import warnings
import re
import time
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

warnings.filterwarnings('ignore')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

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

    cap = cv2.VideoCapture(video_path)
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


print("\n" + "="*70)
print("🎓 VIDEO/AUDIO TO SUMMARY - COMPLETE PIPELINE")
print("="*70)


# ==================== STEP 0: INPUT SELECTION ====================

def get_input_file():
    """YouTube ya local file select karo"""

    print("\n📌 SELECT INPUT:\n")
    print("1️⃣  YouTube Link")
    print("2️⃣  File from 'input' folder")
    print()
    choice = input("Enter choice (1/2): ").strip()

    if choice == "1":
        url = input("\n🔗 Enter YouTube URL: ").strip()
        if not url or ("youtube.com" not in url and "youtu.be" not in url):
            print("❌ Invalid YouTube URL!")
            return None, None, None
        return "youtube", url, url

    elif choice == "2":
        input_dir = Path("input")
        input_dir.mkdir(exist_ok=True)

        supported = ('*.mp4','*.avi','*.mkv','*.mov','*.flv',
                     '*.wav','*.mp3','*.flac','*.m4a')
        files = []
        for fmt in supported:
            files.extend(input_dir.glob(fmt))

        if not files:
            print(f"\n❌ No media files in 'input' folder!")
            print(f"📂 Location: {os.path.abspath('input')}/")
            print("💡 Copy video/audio files there and run again.")
            return None, None, None

        print(f"\n📂 Found {len(files)} file(s):\n")
        for i, f in enumerate(files, 1):
            size = f.stat().st_size / (1024*1024)
            print(f"  {i}. {f.name} ({size:.1f} MB)")

        if len(files) == 1:
            sel = files[0]
        else:
            idx = input(f"\nEnter number (1-{len(files)}): ").strip()
            try:
                sel = files[int(idx)-1]
            except:
                print("❌ Invalid choice!")
                return None, None, None

        print(f"\n✅ Selected: {sel.name}")
        return "local_file", str(sel), sel.stem

    else:
        print("❌ Invalid choice!")
        return None, None, None


# ==================== STEP 1: DOWNLOAD / PREPARE ====================

def prepare_video(source_type, source, output_dir="./downloads"):
    """YouTube download ya local file prepare karo"""

    Path(output_dir).mkdir(exist_ok=True)

    if source_type == "youtube":
        from yt_dlp import YoutubeDL

        print(f"\n{'='*70}")
        print("STEP 1: DOWNLOADING VIDEO")
        print('='*70)

        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'quiet': False,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info      = ydl.extract_info(source, download=True)
            path      = ydl.prepare_filename(info)
            title     = info.get('title', 'video')
            duration  = info.get('duration', 0)

        print(f"\n✅ Download complete!")
        print(f"📊 Title: {title} | Duration: {duration}s")
        return path, title

    else:  # local_file
        print(f"\n{'='*70}")
        print("STEP 1: PREPARING LOCAL FILE")
        print('='*70)

        title = Path(source).stem
        print(f"✅ Using: {Path(source).name}")
        return source, title


# ==================== STEP 2: TRANSCRIBE (GROQ) ====================

def transcribe(video_path, api_key=None):
    """Groq Whisper large-v3 se transcribe karo"""

    from groq import Groq

    print(f"\n{'='*70}")
    print("STEP 2: TRANSCRIBING (GROQ WHISPER large-v3)")
    print('='*70)
    print(f"📂 File: {video_path}")

    key = api_key or GROQ_API_KEY
    if not key:
        print("❌ GROQ_API_KEY not found!")
        return None, None

    # Audio extract + compress
    audio_path = str(Path(video_path).with_suffix('')) + '_temp.mp3'
    print("🔄 Extracting audio...")
    subprocess.run([
        'ffmpeg', '-i', video_path,
        '-ar', '16000', '-ac', '1', '-b:a', '32k',
        audio_path, '-y'
    ], capture_output=True)

    if not os.path.exists(audio_path):
        print("❌ Audio extraction failed!")
        return None, None

    size_mb = os.path.getsize(audio_path) / (1024*1024)
    print(f"📊 Audio size: {size_mb:.1f} MB")

    try:
        client = Groq(api_key=key)
        print("⚡ Sending to Groq Whisper large-v3...")

        if size_mb > 24:
            # Chunked
            chunk_dir = "downloads/chunks"
            Path(chunk_dir).mkdir(parents=True, exist_ok=True)
            subprocess.run([
                'ffmpeg', '-i', audio_path,
                '-f', 'segment', '-segment_time', '300',
                '-c', 'copy', f'{chunk_dir}/chunk_%03d.mp3', '-y'
            ], capture_output=True)

            chunks    = sorted(Path(chunk_dir).glob("chunk_*.mp3"))
            full_text = ""
            print(f"📦 {len(chunks)} chunks created")

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
            print("✅ Chunked transcription complete!")
            return full_text.strip(), "auto"

        # Normal
        with open(audio_path, 'rb') as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model="whisper-large-v3",
                response_format="text",
            )

        os.remove(audio_path)

        print(f"\n📝 TRANSCRIPT PREVIEW:")
        print("-" * 70)
        print(transcription[:500] + "..." if len(transcription) > 500 else transcription)
        print("-" * 70)
        print(f"✅ Done! ({len(transcription)} chars)")
        return transcription, "auto"

    except Exception as e:
        print(f"❌ Groq Whisper error: {e}")
        if os.path.exists(audio_path):
            os.remove(audio_path)
        return None, None


# ==================== STEP 3: GLOSSARY ====================

MASTER_GLOSSARY = {
    "git":        "version control system for tracking code changes",
    "github":     "web-based hosting service for git repositories",
    "repo":       "repository - folder containing project files",
    "commit":     "save a snapshot of changes to the repository",
    "branch":     "parallel version of code in same repository",
    "merge":      "combine changes from different branches",
    "push":       "upload local changes to remote repository",
    "pull":       "download latest changes from remote repository",
    "clone":      "copy entire repository to local machine",
    "fork":       "create independent copy of someone else's repository",
    "ml":         "machine learning - systems that learn from data",
    "ai":         "artificial intelligence - machines doing intelligent tasks",
    "dl":         "deep learning - using neural networks with many layers",
    "nlp":        "natural language processing - computer understanding language",
    "cv":         "computer vision - machines understanding images",
    "llm":        "large language model - AI trained on massive text data",
    "gpt":        "generative pre-trained transformer - LLM architecture",
    "cnn":        "convolutional neural network - for image processing",
    "rnn":        "recurrent neural network - for sequence data",
    "lstm":       "long short-term memory - advanced RNN type",
    "gan":        "generative adversarial network - for creating images",
}

def expand_glossary(transcript):
    print(f"\n{'='*70}")
    print("STEP 3: AUTO GLOSSARY EXPANSION")
    print('='*70)

    found    = []
    expanded = transcript

    for term, defn in MASTER_GLOSSARY.items():
        pattern = rf'\b{re.escape(term)}\b'
        if re.search(pattern, transcript, flags=re.IGNORECASE):
            found.append(term)
            replacement = f"{term.upper()} ({defn})"
            expanded = re.sub(pattern, replacement, expanded, count=1, flags=re.IGNORECASE)

    if found:
        print(f"📚 Expanded {len(found)} terms: {', '.join(t.upper() for t in found)}")
    else:
        print("ℹ️ No technical terms found")

    print("✅ Glossary expansion complete!")
    return expanded


# ==================== STEP 4: GROQ SUMMARY ====================

def groq_summary(transcript, lang, mode, api_key=None, visual_context=None):
    """Groq se abstractive summary generate karo"""

    from groq import Groq

    print(f"\n{'='*70}")
    print(f"STEP 4: GENERATING SUMMARY ({mode.upper()})")
    print('='*70)

    key = api_key or GROQ_API_KEY
    if not key:
        print("❌ GROQ_API_KEY not found!")
        return None

    lang_inst = {
        "en":       "Respond in English only.",
        "hi":       "Respond in Hindi (Devanagari) only.",
        "hinglish": "Respond in Hinglish (Hindi+English mix).",
    }.get(lang, "Respond in English only.")

    if mode == "brief":
        para_sentences = 4
        points_count   = 5
        detail_inst    = "Keep it concise and to the point."
    else:
        para_sentences = 7
        points_count   = 8
        detail_inst    = "Be detailed with context and examples."

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

    client = Groq(api_key=key)
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000
    )
    raw = r.choices[0].message.content.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw).strip()

    result = json.loads(raw)

    print("\n📝 PARAGRAPH:")
    print("-"*70)
    print(result.get("paragraph",""))
    print("-"*70)
    print("\n🔑 KEY POINTS:")
    for pt in result.get("points",[]):
        print(f"  • {pt}")
    print(f"\n💡 TAKEAWAY: {result.get('takeaway','')}")
    print("\n✅ Summary complete!")

    return result


# ==================== SAVE FILES ====================

def save_files(source_type, source, title, transcript, expanded, summary, mode="brief", visual_context=None, lang="en"):
    """Saari files save karo"""

    print(f"\n{'='*70}")
    print("SAVING FILES")
    print('='*70)

    Path("output").mkdir(exist_ok=True)

    # Safe filename
    base = re.sub(r'[<>:"/\\|?*]', '_', title)[:50].strip()

    # Transcript
    p = f"output/{base}_transcript.txt"
    with open(p, "w", encoding='utf-8') as f:
        f.write(f"Source: {source_type}\n\n")
        f.write(transcript or "")
    print(f"✅ {p}")

    # Expanded
    p = f"output/{base}_expanded.txt"
    with open(p, "w", encoding='utf-8') as f:
        f.write(expanded or "")
    print(f"✅ {p}")

    # Summary TXT
    p = f"output/{base}_summary.txt"
    with open(p, "w", encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write(f"SUMMARY: {title}\n")
        f.write("="*70 + "\n\n")
        f.write("PARAGRAPH:\n")
        f.write(summary.get("paragraph","") + "\n\n")
        f.write("KEY POINTS:\n")
        for pt in summary.get("points",[]):
            f.write(f"  • {pt}\n")
        f.write(f"\nTAKEAWAY:\n{summary.get('takeaway','')}\n")
    print(f"✅ {p}")

    # Summary JSON
    p = f"output/{base}_summary.json"
    with open(p, "w", encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"✅ {p}")

    # Latest ke liye bhi save karo (audio/video overview ke liye)
    with open("output/latest_transcript.txt", "w", encoding="utf-8") as f:
        f.write(transcript or "")
    with open("output/latest_meta.json", "w", encoding="utf-8") as f:
        json.dump({
            "url": source, "title": title,
            "lang": lang, "mode": mode,
            "has_audio": bool(transcript and len(transcript) > 10),
            "visual_context": visual_context or ""
        }, f)
    print("✅ output/latest_transcript.txt (for audio/video overview)")


# ==================== MAIN ====================

if __name__ == "__main__":

    total_start = time.time()

    # INPUT
    source_type, source, filename = get_input_file()
    if not source_type:
        exit()

    # STEP 1: Prepare
    t1 = time.time()
    video_path, title = prepare_video(source_type, source)
    if not video_path:
        exit()
    t1_done = time.time() - t1

    # Mode select
    print("\n⏱️ Mode select karo:")
    print("  1. Brief   (concise)")
    print("  2. Detailed (thorough)")
    mode_choice = input("Choice (1/2): ").strip()
    mode = "detailed" if mode_choice == "2" else "brief"

    # STEP 2: Transcribe
    t2 = time.time()
    audio_exists   = has_audio(video_path)
    transcript     = ""
    visual_context = None

    if audio_exists:
        print("🎤 Audio detected — transcribing...")
        transcript, _ = transcribe(video_path, GROQ_API_KEY)
    else:
        print("🔇 No audio detected — switching to visual mode...")
    t2_done = time.time() - t2

    # Always extract frames and analyze visually
    t_vision_start = time.time()
    print("👁️ Extracting and analyzing frames...")
    frames         = extract_key_frames(video_path, max_frames=10)
    visual_context = analyze_frames_with_vision(frames, GROQ_API_KEY)
    t_vision_done  = time.time() - t_vision_start

    # STEP 3: Glossary
    t3 = time.time()
    expanded = expand_glossary(transcript) if transcript else ""
    t3_done = time.time() - t3

    # STEP 4: Summary
    t4 = time.time()
    summary = groq_summary(transcript, lang="en", mode=mode, api_key=GROQ_API_KEY, visual_context=visual_context)
    if not summary:
        exit()
    t4_done = time.time() - t4

    # SAVE
    save_files(source_type, source, title, transcript, expanded, summary, mode=mode, visual_context=visual_context)

    # TIME BREAKDOWN
    total = time.time() - total_start
    print(f"\n{'='*70}")
    print("⏱️  TIME BREAKDOWN")
    print('='*70)
    print(f"  📥 Download/Prepare : {t1_done:.1f}s")
    print(f"  🎤 Transcribe       : {t2_done:.1f}s")
    print(f"  👁️ Vision Pipeline   : {t_vision_done:.1f}s")
    print(f"  📚 Glossary         : {t3_done:.1f}s")
    print(f"  📝 Summary          : {t4_done:.1f}s")
    print(f"  {'─'*35}")
    print(f"  ✅ TOTAL            : {total:.1f}s ({total/60:.1f} min)")
    print('='*70)
    print("\n✨ Done!\n")