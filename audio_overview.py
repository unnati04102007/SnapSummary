# audio_overview.py - AUDIO OVERVIEW WITH LANGUAGE + TIME SELECTION

import os
import json
import asyncio
import requests
from pathlib import Path
from groq import Groq
from tavily import TavilyClient
import edge_tts
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

print("\n" + "="*70)
print("🎧 AUDIO OVERVIEW GENERATOR")
print("="*70)


# ==================== STEP 1: LOAD SUMMARY ====================

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
    """User se language aur duration poocho"""
    
    print(f"\n{'='*70}")
    print("SELECT OPTIONS")
    print('='*70)
    
    # Language
    print("\n🌐 Language select karo:")
    print("  1. English")
    print("  2. Hindi")
    print("  3. Hinglish (Hindi+English mix)")
    
    lang_choice = input("\nChoice (1/2/3): ").strip()
    
    lang_map = {
        "1": {"name": "English", "code": "en", "voice": "en-IN-NeerjaNeural"},
        "2": {"name": "Hindi", "code": "hi", "voice": "hi-IN-SwaraNeural"},
        "3": {"name": "Hinglish", "code": "hinglish", "voice": "hi-IN-MadhurNeural"},
    }
    language = lang_map.get(lang_choice, lang_map["1"])
    print(f"✅ Language: {language['name']}")
    
    # Duration
    print("\n⏱️ Duration select karo:")
    print("  1. Brief (1 min) - Key points only")
    print("  2. Detailed (3 min) - Web se extra info bhi")
    
    dur_choice = input("\nChoice (1/2): ").strip()
    
    dur_map = {
        "1": {"name": "Brief", "words": 120, "detailed": False},
        "2": {"name": "Detailed", "words": 400, "detailed": True},
    }
    duration = dur_map.get(dur_choice, dur_map["1"])
    print(f"✅ Mode: {duration['name']}")
    
    return language, duration


# ==================== STEP 3: WEB FETCH (DETAILED ONLY) ====================

def fetch_web_info(summary):
    """Tavily se relevant extra info fetch karo"""
    
    print(f"\n{'='*70}")
    print("STEP 3: FETCHING WEB INFO (DETAILED MODE)")
    print('='*70)
    
    # Topic extract karo summary se
    groq_client = Groq(api_key=GROQ_API_KEY)
    
    topic_response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{
            "role": "user",
            "content": f"Extract the main topic in 4-5 words only from this summary. Reply with ONLY the topic, nothing else:\n{summary[:500]}"
        }],
        max_tokens=20
    )
    
    topic = topic_response.choices[0].message.content.strip()
    print(f"🔍 Topic detected: {topic}")
    
    # Tavily search
    try:
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        results = tavily.search(
            query=topic,
            max_results=3,
            search_depth="basic"
        )
        
        web_text = ""
        for r in results['results']:
            web_text += r['content'][:300] + " "
        
        print(f"✅ Web info fetched ({len(web_text)} chars)")
        return web_text
    
    except Exception as e:
        print(f"⚠️ Web fetch failed: {e}")
        return ""


# ==================== STEP 4: SCRIPT GENERATION ====================

def generate_script(summary, transcript, web_info, language, duration):
    """Groq se audio script banao"""
    
    print(f"\n{'='*70}")
    print("STEP 4: GENERATING AUDIO SCRIPT")
    print('='*70)
    
    groq_client = Groq(api_key=GROQ_API_KEY)
    
    # Language specific instructions
    lang_instructions = {
        "en": "Write ONLY in English. Clear, natural speaking style.",
        "hi": "Write ONLY in Hindi (Devanagari script). Natural Hindi speaking style.",
        "hinglish": "Write in Hinglish (Hindi+English mix). Natural conversational style jaise koi dost explain kar raha ho."
    }
    
    web_section = f"\nADDITIONAL WEB INFO:\n{web_info}" if web_info else ""
    
    prompt = f"""
You are creating an audio overview script for a YouTube video.

SUMMARY:
{summary}

TRANSCRIPT EXCERPT:
{transcript[:500]}
{web_section}

INSTRUCTIONS:
- {lang_instructions[language['code']]}
- Target length: exactly {duration['words']} words
- Style: Clear narrator, NOT a podcast conversation
- NO filler words like "um", "uh", "you know"
- NO irrelevant information - stick to the topic ONLY
- Start directly with the topic, no intro like "Hello everyone"
- Structure: Main topic → Key points → Takeaway
- Make it engaging and student-friendly

Write ONLY the script, nothing else.
"""
    
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600
    )
    
    script = response.choices[0].message.content.strip()
    
    print(f"✅ Script generated ({len(script.split())} words)")
    print(f"\n📝 SCRIPT PREVIEW:")
    print("-"*70)
    print(script[:300] + "...")
    print("-"*70)
    
    return script


# ==================== STEP 5: TEXT TO SPEECH ====================

async def generate_audio(script, voice, output_path):
    """edge-tts se audio banao"""
    
    print(f"\n{'='*70}")
    print("STEP 5: GENERATING AUDIO")
    print('='*70)
    print(f"🎙️ Voice: {voice}")
    
    communicate = edge_tts.Communicate(script, voice)
    await communicate.save(output_path)
    
    print(f"✅ Audio saved: {output_path}")


# ==================== MAIN ====================

if __name__ == "__main__":
    
    # Load summary
    summary, transcript = load_files()
    if not summary:
        exit()
    
    # User options
    language, duration = get_user_options()
    
    # Web fetch (only detailed mode)
    web_info = ""
    if duration['detailed']:
        web_info = fetch_web_info(summary)
    
    # Script generate
    script = generate_script(summary, transcript, web_info, language, duration)
    
    # Save script
    Path("output").mkdir(exist_ok=True)
    with open("output/audio_script.txt", "w", encoding='utf-8') as f:
        f.write(script)
    print("✅ Script saved: output/audio_script.txt")
    
    # Audio generate
    audio_path = "output/audio_overview.mp3"
    asyncio.run(generate_audio(script, language['voice'], audio_path))
    
    # Done
    print(f"\n{'='*70}")
    print("✨ AUDIO OVERVIEW COMPLETE!")
    print('='*70)
    print(f"\n📂 Output files:")
    print(f"   ├── output/audio_script.txt  (script)")
    print(f"   └── output/audio_overview.mp3 (audio)")
    print(f"\n▶️ Play: output/audio_overview.mp3")