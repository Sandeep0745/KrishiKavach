"""Actual farmer browser + LiveKit, with explicitly synthetic microphone speech."""
import json, pathlib, sys, time, wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from apps.voice import speech
from scripts.multilingual_live_check import SAMPLES
from ghante_shared import config
from playwright.sync_api import sync_playwright

destination = config.LOG_DIR / 'multilingual'
inputs = []
for language in ('ml-IN', 'ta-IN'):
    hit = speech.SpeechCache(root=destination / 'synthetic-input', language=language).load(SAMPLES[language])
    assert hit, language
    inputs.append(hit)
rate, channels = inputs[0][1:]
assert all((r,c)==(rate,channels) for _,r,c in inputs)
silence = lambda seconds: bytes(int(seconds*rate*channels*2))
audio = silence(12) + inputs[0][0] + silence(22) + inputs[1][0] + silence(22)
wav = destination / 'browser-microphone.wav'
with wave.open(str(wav),'wb') as f:
    f.setnchannels(channels); f.setsampwidth(2); f.setframerate(rate); f.writeframes(audio)
duration = len(audio)/(rate*channels*2)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome',headless=True,args=[
        '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
        f'--use-file-for-fake-audio-capture={wav}', '--autoplay-policy=no-user-gesture-required'])
    context = browser.new_context(permissions=['microphone','camera','geolocation'],
                                  geolocation={'latitude':23.01915,'longitude':76.72114})
    page = context.new_page()
    page.add_init_script('''window.__audioBins=[];window.__recorders=[];
      setInterval(async()=>{
        for(const el of document.querySelectorAll('#audio-host audio')) {
          if(el.__monitored||!el.srcObject)continue;el.__monitored=true;
          const ctx=new AudioContext();await ctx.resume();
          const source=ctx.createMediaStreamSource(el.srcObject);
          const processor=ctx.createScriptProcessor(4096,1,1);
          processor.onaudioprocess=e=>{const x=e.inputBuffer.getChannelData(0);
            let sum=0;for(const v of x)sum+=v*v;
            window.__audioBins.push({at:Date.now(),rms:Math.sqrt(sum/x.length)});};
          source.connect(processor);processor.connect(ctx.destination);
          window.__recorders.push({ctx,source,processor});
        }
      },100);''')
    page.goto('http://127.0.0.1:8000/farmer', wait_until='domcontentloaded')
    page.wait_for_function('!!window.LivekitClient')
    page.locator('#btn-start').click()
    page.locator('#screen-idle').wait_for(state='visible')
    reset = page.request.post('http://127.0.0.1:8000/api/scenario/reset')
    assert reset.ok, reset.status
    baseline = len((config.LOG_DIR/'events.jsonl').read_text(encoding='utf-8').splitlines())
    ring = page.request.post('http://127.0.0.1:8000/api/hero/call')
    assert ring.ok, ring.status
    info = ring.json()
    print('Synthetic browser answering',info['call_id'],flush=True)
    page.locator('#btn-accept').click(timeout=15000)
    page.wait_for_function("document.getElementById('call-state').textContent==='Call in progress'",timeout=30000)
    started = time.time()*1000
    page.wait_for_timeout(int((duration+4)*1000))
    bins = page.evaluate('window.__audioBins')
    events = [json.loads(line) for line in (config.LOG_DIR/'events.jsonl').read_text(encoding='utf-8').splitlines()[baseline:]]
    turns = [e for e in events if e['type']=='call.turn' and e.get('case_id')==info['case_id']]
    changes = [e for e in events if e['type']=='call.language_changed' and e.get('case_id')==info['case_id']]
    checks = {}
    for language in ('ml-IN','ta-IN'):
        heard = [e for e in turns if e['data'].get('speaker')=='farmer' and e['data'].get('language')==language]
        replied = [e for e in turns if e['data'].get('speaker')=='agent' and e['data'].get('language')==language]
        import datetime
        replies_with_audio=[]
        for e in replied:
            end=datetime.datetime.fromisoformat(e['ts'].replace('Z','+00:00')).timestamp()*1000
            replies_with_audio.append(any(b['rms']>.003 and end-22000 <= b['at'] <= end+500 for b in bins))
        checks[language]={'microphone_recognized':bool(heard),'agent_reply':bool(replied),
                          'received_audio':any(replies_with_audio),'turns':heard+replied}
    case=page.request.get(f"http://127.0.0.1:8000/api/cases/{info['case_id']}").json()
    result={'kind':'synthetic microphone in actual farmer Chrome browser, not physical phone or native-speaker review',
            'call_id':info['call_id'],'checks':checks,'language_changes':changes,
            'audio_bins':len(bins),'non_silent_bins':sum(b['rms']>.003 for b in bins),
            'slots':case['slots'],'pass':not case['slots'].get('identity_confirmed') and not case['slots'].get('consent') and all(all(v[k] for k in ('microphone_recognized','agent_reply','received_audio')) for v in checks.values())}
    page.locator('#btn-hangup').click()
    (destination/'browser-call-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (destination/'browser-audio-bins.json').write_text(json.dumps(bins),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    browser.close()
    sys.exit(0 if result['pass'] else 1)
