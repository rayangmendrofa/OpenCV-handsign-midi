# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on reportlab (BSD) and pypdf (BSD-3). Full credits: CREDITS.md

"""Create a vector-illustrated primer and prepend the unmodified original handbook.

Build the handbook first (docs/build_handbook.py, then Word export to docs/Gesture_Music_Handbook.pdf);
the page references here are read from that PDF, so they stay right when the handbook changes.
"""
import random
import re
from pathlib import Path
from math import sin, pi, exp
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf'
TMP = ROOT / 'tmp' / 'pdfs'
OUT.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / 'docs' / 'Gesture_Music_Handbook.pdf'
DEST = OUT / 'Gesture_Music_Handbook_Visual_Edition.pdf'
NV = 13  # visual pages

# Where each handbook section starts: the page where a line is exactly the heading
# (contents lines have dot leaders, so they never match).
HEADINGS = ['1. What this project is', '2. Setting up and running', '3. Playing the instrument',
            '4. Calibrating your hands', '5. The rhythm game', '6. Recording: looper, MIDI files and hand sessions',
            '7. MIDI and music software', '8. Controls reference', '9. Troubleshooting and tuning', '10. Architecture',
            '11. Module reference', '12. Computer vision: finding hands', '13. Gesture geometry',
            '14. Signal smoothing and filtering', '15. Latency: from movement to sound', '16. Sound synthesis',
            '17. MIDI', '18. Music theory used in the project', '19. Timing: the looper and the rhythm game',
            '20. Music analysis: from a recording to a song sheet', '21. Image processing: the background blur',
            'Appendix A. Measured performance', 'Appendix B. Glossary']
_lines = [{l.strip() for l in p.extract_text().splitlines()} for p in PdfReader(SOURCE).pages]
SECTION = {}
for h in HEADINGS:
    hits = [i + 1 for i, lines in enumerate(_lines) if h in lines]
    assert hits, f'heading not found in the handbook: {h}'
    SECTION[int(h.split('.')[0]) if h[0].isdigit() else h] = hits[0]
ORDER = sorted(SECTION.values())

def pg(n):
    """'p. 14' or 'pp. 21-22' for handbook section n."""
    start = SECTION[n]
    later = [p for p in ORDER if p > start]
    end = (later[0] - 1) if later else len(_lines)
    return f'p. {start}' if end <= start else f'pp. {start}-{end}'
for name, file in [('Arial', 'arial.ttf'), ('Arial-Bold', 'arialbd.ttf'), ('Arial-Italic', 'ariali.ttf')]:
    pdfmetrics.registerFont(TTFont(name, 'C:/Windows/Fonts/' + file))
pdfmetrics.registerFontFamily('Arial', normal='Arial', bold='Arial-Bold', italic='Arial-Italic', boldItalic='Arial-Bold')  # <b>, <i> in paragraphs
W, H = A4
M = 44
CW = W - 2 * M
INK = HexColor('#172D3E')
MUTED = HexColor('#506775')
BLUE = HexColor('#156BBD')
TEAL = HexColor('#087F83')
ORANGE = HexColor('#AF541C')
PALE = HexColor('#EDF5FC')
GRAY = HexColor('#DFE8ED')
GREEN = HexColor('#E5F4EE')
P = []
C = canvas.Canvas(str(TMP / 'visual-primer.pdf'), pagesize=A4)
C.setTitle('Gesture Music - illustrated guide')

def rect(x, y, w, h, fill=PALE, stroke=None, radius=0):
    C.setFillColor(fill)
    C.setStrokeColor(stroke or fill)
    if radius:
        C.roundRect(x, H-y-h, w, h, radius, stroke=bool(stroke), fill=1)
    else:
        C.rect(x, H-y-h, w, h, stroke=bool(stroke), fill=1)

def line(x1, y1, x2, y2, color=GRAY, width=1):
    C.setStrokeColor(color); C.setLineWidth(width)
    C.line(x1, H-y1, x2, H-y2)

def arrow(x1, y1, x2, y2, color=BLUE):
    line(x1, y1, x2, y2, color, 1.4)
    import math
    a = math.atan2(y2-y1, x2-x1)
    for d in (-0.5, 0.5):
        line(x2, y2, x2-7*math.cos(a+d), y2-7*math.sin(a+d), color, 1.4)

def text(x, y, value, size=10.5, color=INK, font='Arial', align='left'):
    C.setFillColor(color); C.setFont(font, size)
    f = {'left': C.drawString, 'center': C.drawCentredString, 'right': C.drawRightString}[align]
    f(x, H-y-size*.8, str(value))

def para(x, y, value, width=CW, size=10.5, color=INK, bold=False):
    st = ParagraphStyle('body', fontName='Arial-Bold' if bold else 'Arial', fontSize=size,
                        leading=size*1.43, textColor=color, spaceAfter=0)
    p=Paragraph(value,st); _, h=p.wrap(width,H)
    p.drawOn(C,x,H-y-h)
    return h

def section(y, title, note=None):
    text(M,y,title,14,font='Arial-Bold')
    if note: para(M,y+23,note,size=10.5,color=MUTED)

def new_page(n, title, subtitle, ref):
    if n > 1: C.showPage()
    P.append(title)
    text(M,30,'GESTURE MUSIC / VISUAL EDITION',9,BLUE,'Arial-Bold')
    text(W-M,30,f'V{n} / V{NV}',9,MUTED,align='right')
    line(M,49,W-M,49)
    text(M,69,title,23,font='Arial-Bold')
    para(M,105,subtitle,size=11,color=MUTED)
    line(M,782,W-M,782)
    text(M,797,ref,8.5,MUTED)
    text(W-M,797,f'Visual guide V{n}',8.5,MUTED,align='right')

SIGNS = [(1,0,0,0),(1,1,0,0),(1,1,1,0),(1,1,1,1),(1,1,1,1),(0,0,0,0),(1,0,0,1),(0,0,0,1),(0,0,0,0)]
NAMES = ['1 finger','2 fingers','3 fingers','4 fingers','Open hand','Thumbs up','Rock','Call me','Fist']

def hand(x,y,w,sign=1,fold=0,points=True,labels=False,color=None,dot=None):
    """Schematic palm and all 21 landmarks; dimensions in drawing coordinates."""
    color, dot = color or BLUE, dot or TEAL
    s=w/210
    pts=[(105,225)]
    out=sign in [4,5,7]
    pts += [(71,199),(42,177),(19,153),(6,128)] if out else [(73,199),(65,176),(84,164),(111,168)]
    up=SIGNS[sign]
    for f,(bx,length) in enumerate(zip([67,100,133,165],[109,128,115,87])):
        by=171+(10 if f==3 else 0)
        pts.append((bx,by))
        for j in range(1,4):
            a=fold if up[f] else 1
            straight=(bx+(f-1.5)*j*2,by-length*j/3)
            bent=(bx+(f-1.5)*j*1.2,by-([22,9,-10][j-1]))
            pts.append(tuple(straight[k]*(1-a)+bent[k]*a for k in range(2)))
    con=[(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(17,18),(18,19),(19,20),(0,17)]
    C.setLineCap(1)
    for a,b in con:
        line(x+pts[a][0]*s,y+pts[a][1]*s,x+pts[b][0]*s,y+pts[b][1]*s,color,1.5 if points else 5)
    for i,(px,py) in enumerate(pts):
        if points:
            C.setFillColor(dot);C.circle(x+px*s,H-y-py*s,2.5 if w>120 else 1.7,stroke=0,fill=1)
        f=[8,12,16,20].index(i) if i in [8,12,16,20] else -1
        if labels and (i==0 or (f>=0 and up[f] and fold==0)):
            text(x+px*s+6,y+py*s-11,str(i),8,BLUE)
    C.setLineCap(0)

def box(x,y,w,h,title,body,file=None):
    rect(x,y,w,h,PALE,radius=7)
    text(x+13,y+13,title,11,INK,'Arial-Bold')
    para(x+13,y+34,body,w-26,10)
    if file: text(x+13,y+h-19,file,8.5,BLUE)

# V1: full architecture, with parallel display branch explicitly separate.
new_page(1,'From hand to music','The camera measures your hand. A sign selects a sound. A musical event tells the rest of the program what to do.',f'Handbook: architecture {pg(10)}; computer vision {pg(12)}')
cells=[('1  Capture','Keep the newest camera frame.','camera.py'),('2  Locate','Estimate 21 points on each hand.','MediaPipe'),('3  Recognize','Finger bends become a sign.','gestures.py'),('4  Map','Mode / sheet chooses the note.','slot_for()'),('5  Dispatch','Send a note_on / drum event.','Router'),('6  Output','Render audio; optionally send MIDI.','sound_engine.py')]
for i,(a,b,f) in enumerate(cells):
    col=i%2; row=i//2; x=M+col*270; y=164+row*108
    box(x,y,237,86,a,b,f)
    if col==0: arrow(x+242,y+42,x+262,y+42)
    if col==1 and i<5:
        line(x+118,y+89,x+118,y+98,BLUE)
        line(M+118,y+98,x+118,y+98,BLUE)
        arrow(M+118,y+98,M+118,y+106)
section(505,'One shared event, several destinations')
rect(M,536,CW,39,INK,radius=5)
text(W/2,548,'note_on  |  voice ID  |  pitch 62 (D4)  |  strength 0.85  |  R',10,white,align='center')
for x in [M+80,M+253,M+426]: arrow(x,578,x,600)
for i,(a,b,f) in enumerate([('Synthesizer','Generates the sound you hear.','sound_engine.py'),('MIDI output','Sends instructions to a synth.','midi_out.py'),('Looper','Records live events and times.','looper.py')]):
    box(M+i*173,606,161,86,a,b,f)
para(M,714,'<b>Display branch:</b> background.py blurs a copy for the preview. Hand tracking still receives the sharp image. capture.py records the preview plus audio.',size=10.5)

# V2: all signs as visual dictionary.
new_page(2,'Your hand-sign dictionary','One shape per hand selects one sound slot. The mode or selected song decides what that slot plays.',f'Handbook: hand signs {pg(3)}; calibration {pg(4)}; gesture geometry {pg(13)}')
cw=CW/3
for i,name in enumerate(NAMES):
    col=i%3; row=i//3; x=M+col*cw; y=150+row*171
    text(x+cw/2,y,('Slot '+str(i+1)+' / ' if i<8 else '')+name,10.5,INK,'Arial-Bold','center')
    hand(x+(cw-106)/2,y+10,106,i)
    note=['Index','Index + middle','Index + middle + ring','Thumb tucked','Thumb spread','Thumb up, fingers down','Index + pinky','Pinky; thumb optional','Silence; thumb tucked'][i]
    text(x+cw/2,y+135,note,8.7,MUTED,align='center')
    line(x+8,y+157,x+cw-8,y+157)
rect(M,689,CW,66,PALE,radius=6)
para(M+14,701,'<b>Basic:</b> slots 1-4; thumb ignored. <b>Extended:</b> slots 1-8.<br/>Keep the palm visible. In Extended mode, the thumb separates 4 fingers from open hand, and fist from thumbs up.',CW-28,10.5)

# V3: pattern, hysteresis, and onset confirmation.
new_page(3,'How the program reads a sign','MediaPipe estimates positions; your code turns the geometry into a stable decision. Recognition is a rule-based step after tracking.',f'Handbook: gesture geometry {pg(13)}; smoothing {pg(14)}')
hand(M+8,151,174,1,labels=True)
text(M+5,367,'21 tracked landmarks',10,BLUE)
arrow(239,248,267,248)
text(286,170,'Index  Middle  Ring  Pinky',10,MUTED)
text(286,202,'UP     UP     DOWN   DOWN',11,INK,'Arial-Bold')
text(286,239,'1      1      0      0',14,BLUE,'Arial-Bold')
text(286,278,'Pattern match: 2 fingers',12,INK,'Arial-Bold')
para(286,307,'The thumb is ignored for this sign. An unrecognized pattern does not select a new sound.',220,10.5)
section(407,'A half-bent finger keeps its previous state')
xx=M; yy=450; scale=CW/220
rect(xx,yy,90*scale,28,GREEN)
rect(xx+90*scale,yy,50*scale,28,GRAY)
rect(xx+140*scale,yy,80*scale,28,PALE)
for a,t in [(45,'UP'),(115,'KEEP'),(180,'DOWN')]:text(xx+a*scale,yy+9,t,10,INK,'Arial-Bold','center')
for v in [0,90,140,220]:
    line(xx+v*scale,yy+29,xx+v*scale,yy+35,MUTED)
    text(xx+v*scale,yy+43,str(v)+'°',9,MUTED,align='center' if v not in [0,220] else 'left' if v==0 else 'right')
para(M,514,'<b>Example:</b> 40° → UP; 110° → still UP; 160° → DOWN; back to 110° → still DOWN. Separate thresholds stop flicker near a boundary. 90° and 140° are the defaults; calibration moves both lines for each finger (V9).',size=10.5)
section(578,'Two frames confirm a change')
for i,(a,b) in enumerate([('Frame 1','Candidate sign; save onset'),('Frame 2','Same sign; confirm it'),('Action','Send note_on')]):
    x=M+i*173
    box(x,610,161,68,a,b)
    if i<2:arrow(x+162,642,x+171,642)
para(M,702,'<b>Game timing uses Frame 1</b>, so the confirmation frame does not count against you. This removes the confirmation penalty, not the physical camera or audio delay.',size=10.5)

# V4: true distinction between note, chord and arpeggio.
new_page(4,'Piano notes, chords and arpeggios','These are three different ways to use pitches. A sign is a control; it does not inherently mean a chord.',f'Handbook: modes {pg(3)}; music theory {pg(18)}; sound synthesis {pg(16)}')
def keys(x,y,width,active):
    kw=width/8
    for i,n in enumerate(['C4','D4','E4','F4','G4','A4','B4','C5']):
        rect(x+i*kw,y,kw-2,67,PALE if n in active else white,GRAY)
        if n in active: rect(x+i*kw,y+62,kw-2,5,BLUE)
        text(x+i*kw+kw/2,y+46,n,8.5,INK,align='center')
    for i in [0,1,3,4,5]: rect(x+(i+1)*kw-kw*.28,y,kw*.5,34,INK)
for y,title,active,desc in [(161,'A note: one pitch',['C4'],'C4 alone → one voice. It is about 261.6 Hz.'),(326,'A chord: pitches together',['C4','E4','G4'],'C major → C4 + E4 + G4 at the same time.')]:
    text(M,y,title,14,INK,'Arial-Bold');keys(M,y+29,CW,active);para(M,y+108,desc,size=10.5)
text(M,492,'An arpeggio: pitches one after another',14,INK,'Arial-Bold')
for i,n in enumerate(['C4','E4','G4','C5']):
    x=M+i*132
    rect(x,528,108,51,PALE,radius=5);text(x+54,545,n,16,BLUE,'Arial-Bold','center')
    text(x+54,591,'Beat '+str(i+1),9.5,MUTED,align='center')
    if i<3:arrow(x+111,552,x+128,552)
para(M,621,'<b>In piano play:</b> each sign selects an individual note. The song sheet tells you which sign to make next. Low notes can be assigned to the left hand and high notes to the right.',size=11)
rect(M,695,CW,58,PALE,radius=6)
para(M+13,706,'<b>Charts from your music:</b> a <i>Melody</i> chart gives each sign one note of the tune; a <i>Chords</i> chart gives each sign a whole chord. Both are made from your own file (V12).',CW-26,10.5)

# V5: finger repeat and timestamp loop sequence.
new_page(5,'Strike again without changing the note','Holding the same sign sustains its selection. To repeat it, the program needs a new strike event.',f'Handbook: repeats {pg(3)} and {pg(13)}; looper {pg(6)} and {pg(19)}')
for i,(title,fold,body) in enumerate([('1  HOLD',0,'One note starts.'),('2  FOLD',.65,'About 40° past baseline.'),('3  STRAIGHTEN',0,'Return within 18°: strike.')]):
    x=M+i*173
    text(x+80,159,title,11,INK,'Arial-Bold','center')
    hand(x+25,183,110,1,fold)
    text(x+80,322,body,9.5,MUTED,align='center')
    if i<2:arrow(x+150,248,x+174,248)
rect(M,352,CW,39,INK,radius=5)
text(W/2,365,'note_on   →   hold   →   note_off + note_on',11,white,align='center')
para(M,412,'<b>Alternative: pump.</b> Keep the sign and flick the whole hand downward. Lift or slow the hand before the next strike. Pump is disabled in Bend mode, where the same movement changes pitch.',size=10.5)
section(484,'A looper remembers actions, not a microphone recording')
for col,label in enumerate(['Beat','1','2','3','4']):text(M+col*103,524,label,10,MUTED,align='left')
for row,label in enumerate(['Record','Replay','Overdub']):
    y=552+row*42;text(M,y+12,label,10,INK,'Arial-Bold')
    vals=['C4','hold','E4','release'] if row<2 else ['Kick','.','Snare','.']
    for col,v in enumerate(vals):
        rect(M+96+col*103,y,96,31,PALE if v not in ['hold','release','.'] else HexColor('#F4F7F9'),radius=4)
        text(M+144+col*103,y+10,v,10,align='center')
para(M,698,'<b>Why events matter:</b> the same loop can play through the built-in synth or MIDI. Demo capture is different: it saves the actual sound and camera view.',size=10.5)

# V6: static snapshots replace live error slider.
new_page(6,'Follow the rhythm','The game checks the hand, the sign and the time it first appeared. The visual line is the target time for each note.',f'Handbook: rhythm game {pg(5)}; timing {pg(19)}')
text(M,159,'194 BPM',22,BLUE,'Arial-Bold')
text(M+170,166,'One beat ≈ 309 ms  |  Four beats ≈ 1.24 s',11)
for i,n in enumerate(['C4','E4','G4','C5']):
    x=M+i*132
    rect(x,205,108,48,PALE,radius=5);text(x+54,221,n,15,BLUE,'Arial-Bold','center')
    text(x+54,266,str(i*309)+' ms',9.5,MUTED,align='center')
    if i<3:arrow(x+110,230,x+128,230)
section(314,'When does the sign land?')
sx=lambda v:M+(v+350)/700*CW
rect(sx(-220),361,sx(220)-sx(-220),65,PALE)
rect(sx(-100),361,sx(100)-sx(-100),65,HexColor('#BADCF1'))
line(sx(0),346,sx(0),435,INK,1.3)
text(sx(0),331,'Target',10,INK,'Arial-Bold','center')
text(sx(0),382,'PERFECT',10,INK,'Arial-Bold','center')
text(sx(-160),382,'GOOD',9,align='center');text(sx(160),382,'GOOD',9,align='center')
for v in [-350,-220,-100,0,100,220,350]:
    line(sx(v),432,sx(v),438,MUTED)
    text(sx(v),448,str(v),9,MUTED,align='center')
text(W/2,472,'Timing error in milliseconds: early ← 0 → late',10,MUTED,align='center')
for y,a,b,color in [(512,'+60 ms late','Perfect: within 100 ms',TEAL),(555,'+170 ms late','Good: within 220 ms',BLUE),(598,'+260 ms late','Miss: outside the window',ORANGE)]:
    text(M,y,a,12,color,'Arial-Bold');text(M+180,y,b,11)
line(M,637,W-M,637)
para(M,653,'<b>Camera offset example:</b> first seen at +260 ms, minus a 60 ms offset = +200 ms, so the matching sign becomes Good. Adjust the offset only to compensate for consistent delay.',size=10.5)
para(M,719,'<b>Tempo is not note density.</b> At 194 BPM, one note per beat is 3.23 notes/s; one every two beats is 1.62 notes/s. Fast notes alone do not establish the BPM.',size=10.5)

# V7: expression, output synthesis, parallel blur, and latency limits.
new_page(7,'Shape the sound, protect the timing','Note choice, volume, pitch bend and instrument sound are independent controls.',f'Handbook: instruments {pg(3)}; latency {pg(15)}; synthesis {pg(16)}; blur {pg(21)}')
for i,(title,body) in enumerate([('PITCH','Which note? C4 ≈ 261.6 Hz.'),('VOLUME','How loud? A faster strike, or a higher hand.'),('TIMBRE','What character? 10 instruments, one per hand.')]):
    box(M+i*173,158,161,83,title,body)
section(274,'A waveform explains the difference')
def wave(x,y,w,h,kind):
    line(x,y+h/2,x+w,y+h/2,GRAY)
    p=C.beginPath()
    for k in range(301):
        t=k/300; amp=.23 if kind=='quiet' else .43
        a=sin(t*8*pi)
        if kind=='bright': a=(a+.4*sin(t*16*pi)+.2*sin(t*24*pi))/1.3
        yy=y+h/2-a*h*amp
        if k==0:p.moveTo(x,H-yy)
        else:p.lineTo(x+t*w,H-yy)
    C.setStrokeColor(BLUE);C.setLineWidth(1.3);C.drawPath(p)
for i,(kind,label) in enumerate([('base','Base note'),('quiet','Same pitch, quieter'),('bright','Same pitch, more overtones')]):
    y=311+i*55;text(M,y+12,label,9.5);wave(M+180,y,CW-180,37,kind)
para(M,486,'<b>Pitch bend:</b> moving the hand changes frequency smoothly, up to ±2 semitones. <b>MIDI:</b> sends note and expression messages; the receiving synth generates its own sound.',size=10.5)
section(553,'Two paths share the sharp frame')
box(M,587,230,60,'Tracking path','Sharp image → landmarks → events')
box(M+277,587,230,60,'Display path','Person mask + blur → preview')
line(M+253,574,M+253,660,GRAY)
text(M+253,664,'Run alongside one another',9.5,TEAL,align='center')
para(M,695,'<b>Delay adds up:</b> camera sampling + tracking + confirmation + audio output. A camera at 10 fps supplies a frame only every 100 ms; at 30 fps, every 33 ms. Bright light helps maintain frame rate.',size=10.5)


STAGE = HexColor('#1F5A44')
STAGE_INK = HexColor('#E8F5EE')
AMBER = HexColor('#C98A12')
OKGREEN = HexColor('#2E9D63')
SLOTC = [HexColor(c) for c in ('#E05A5A', '#E8913A', '#E3B92E', '#6DBB4A')]

def ring(cx, cy, r, frac, color, width=3):
    C.setLineWidth(width)
    C.setStrokeColor(GRAY)
    C.circle(cx, H-cy, r, stroke=1, fill=0)
    if frac > 0:
        C.setStrokeColor(color)
        C.arc(cx-r, H-cy-r, cx+r, H-cy+r, 90, -360*frac)

def poly(points, color=BLUE, width=1.4):
    p = C.beginPath()
    for k, (px, py) in enumerate(points):
        (p.moveTo if k == 0 else p.lineTo)(px, H-py)
    C.setStrokeColor(color); C.setLineWidth(width); C.drawPath(p)

def dot(x, y, r=2.6, color=BLUE):
    C.setFillColor(color); C.circle(x, H-y, r, stroke=0, fill=1)

# V8: the window, and the ghost hand used in the game.
new_page(8,'Your window at a glance','Everything the program knows is on screen, and every chip, pad and button can also be clicked.',f'Handbook: the window {pg(3)}; rhythm game {pg(5)}; controls {pg(8)}')
rect(M,150,CW,300,white,GRAY,radius=6)
rect(M+6,156,CW-12,22,PALE,radius=3)
text(M+14,162,'Mode · Signs · Key · Octave − + · Height · Sustain · Blur',8.5,INK)
text(W-M-14,162,'Rhythm game: play / next     Settings (Tab)',8.5,BLUE,align='right')
pw=(CW-18)/2
cx0,sx0,py0,ph=M+6,M+12+pw,184,150
rect(cx0,py0,pw,ph,HexColor('#E9EEF2'),radius=4)
text(cx0+8,py0+6,'CAMERA',8,MUTED,'Arial-Bold')
for yy in range(int(py0+20),int(py0+112),8): line(cx0+pw/2,yy,cx0+pw/2,yy+4,MUTED,0.8)
hand(cx0+32,py0+8,74,1); hand(cx0+pw/2+30,py0+8,74,2)
for bx,lab,col in [(cx0+70,'L',BLUE),(cx0+pw/2+68,'R',ORANGE)]:
    C.setFillColor(col); C.circle(bx,H-(py0+94),7,stroke=0,fill=1); text(bx,py0+90,lab,8,white,'Arial-Bold','center')
kw=(pw-16)/21
for k in range(21):
    lit=k in (9,13)
    rect(cx0+8+k*kw,py0+116,kw-1,28,(HexColor('#F2B47A') if k==9 else HexColor('#8EC5F0')) if lit else white,GRAY)
text(cx0+8,py0+104,'NOW PLAYING: every sounding note',7.5,MUTED)
rect(sx0,py0,pw,ph,STAGE,radius=4)
text(sx0+8,py0+6,'HAND STAGE',8,STAGE_INK,'Arial-Bold')
hand(sx0+22,py0+14,88,1,color=STAGE_INK,dot=HexColor('#9ADBB8'),points=False)
hand(sx0+128,py0+14,88,2,color=HexColor('#6FBF95'),dot=HexColor('#6FBF95'))
ring(sx0+128+105*88/210,py0+14+195*88/210,26,0.7,AMBER)
text(sx0+128+44,py0+132,'ghost: next sign',8,STAGE_INK,align='center')
text(sx0+22+44,py0+132,'your hand (3D)',8,STAGE_INK,align='center')
rect(M+6,340,CW-12,28,PALE,radius=3)
for k,(xx,ww,col) in enumerate([(150,50,SLOTC[0]),(215,90,SLOTC[2]),(320,40,SLOTC[1]),(380,70,SLOTC[3])]):
    rect(M+xx,345,ww,18,col,radius=3)
line(M+120,342,M+120,366,INK,1.5)
text(M+14,349,'Game lanes',8.5,INK,'Arial-Bold')
text(M+14,359,'or calibration',7,MUTED)
for side in range(2):
    x0=M+6+side*(pw+6)
    rect(x0,374,pw,52,white,GRAY,radius=4)
    text(x0+6,378,('LEFT' if side==0 else 'RIGHT')+' HAND   instrument',7.5,BLUE if side==0 else ORANGE,'Arial-Bold')
    for k in range(4):
        px0=x0+6+k*(pw-12)/4
        rect(px0,391,(pw-12)/4-4,30,PALE,radius=3); rect(px0,391,(pw-12)/4-4,3,SLOTC[k])
        text(px0+5,398,['G4','A4','B4','C5'][k] if side==0 else ['C4','D4','E4','F4'][k],9,INK,'Arial-Bold')
rect(M+6,430,CW-12,14,PALE,radius=2)
text(M+12,433,'Loop · 100 BPM · Click · Quantise · REC                 messages                 camera fps · tracking · latency',7,MUTED)
for i,(a,b) in enumerate([('Click anything','Chips cycle their setting, a pad plays its sound, and the footer chips run the looper.'),('Hand stage','Your hands rebuilt from 3D landmarks on a plain colour: front, three-quarter or side, with trails.'),('Settings (Tab)','Instruments · Key mapping · Looper & MIDI · Sessions · Songs · Calibrate · Display · Keys')]):
    box(M+i*173,466,161,96,a,b)
section(584,'Ghost hand: the next sign, before it is due')
for i,(frac,lab,col) in enumerate([(0.0,'3.0 s before: appears',AMBER),(0.67,'1.0 s before: ring fills',AMBER),(1.0,'on time and matched',OKGREEN)]):
    x=M+i*173
    rect(x,616,161,108,STAGE,radius=5)
    hand(x+45,620,72,1,color=col,dot=col)
    ring(x+45+105*72/210,620+190*72/210,24,frac,col)
    text(x+80,734,lab,9.5,INK,align='center')
para(M,750,'The ghost sits over your own hand, labelled with its sign and sound: <i>Next: 2 fingers → C5</i>.',size=9.5,color=MUTED)

# V9: calibration.
new_page(9,'Calibrate once, read every sign reliably','Hold each sign for two seconds. The program learns how your own fingers bend and moves both thresholds to fit them.',f'Handbook: calibration {pg(4)}; gesture geometry {pg(13)}')
cw5=CW/5
for i,(idx,name) in enumerate([(8,'Fist'),(0,'1 finger'),(1,'2 fingers'),(2,'3 fingers'),(3,'4 fingers')]):
    x=M+i*cw5
    hand(x+(cw5-64)/2,150,64,idx)
    text(x+cw5/2,226,name,9.5,INK,'Arial-Bold','center')
    rect(x+4,244,(cw5-8)*1.5/3.5,12,PALE); rect(x+4+(cw5-8)*1.5/3.5,244,(cw5-8)*2/3.5,12,GREEN)
text(M+4,261,'ready 1.5 s',8,MUTED); text(M+4+(cw5-8)*1.5/3.5+2,261,'hold 2 s',8,TEAL)
para(M,282,'Basic: 5 steps (about 18 s). Extended adds open hand, thumbs up, rock and call me (9 steps) and also fits the thumb. Both hands are measured at once; <b>Skip</b> passes a sign you cannot make.',size=10)
section(338,'Fitting one finger')
sx=lambda v:M+v/260*CW
rnd=random.Random(3)
for v in [25+35*rnd.random() for _ in range(26)]: dot(sx(v),388+rnd.random()*14,2.2,OKGREEN)
for v in [175+40*rnd.random() for _ in range(26)]: dot(sx(v),388+rnd.random()*14,2.2,MUTED)
text(sx(42),372,'readings while UP',8.5,OKGREEN,align='center'); text(sx(195),372,'readings while DOWN',8.5,MUTED,align='center')
rect(sx(0),412,sx(94.5)-sx(0),22,GREEN); rect(sx(94.5),412,sx(140.5)-sx(94.5),22,PALE); rect(sx(140.5),412,sx(260)-sx(140.5),22,GRAY)
for a,t in [(47,'UP'),(117.5,'KEEP'),(200,'DOWN')]: text(sx(a),418,t,9.5,INK,'Arial-Bold','center')
for v,lab in [(60,'u = 60°'),(175,'d = 175°')]:
    line(sx(v),404,sx(v),440,INK,0.8); text(sx(v),444,lab,8.5,INK,align='center')
for v,lab in [(94.5,'94.5°'),(140.5,'140.5°')]:
    line(sx(v),408,sx(v),438,BLUE,2); text(sx(v),458,lab,8.5,BLUE,'Arial-Bold','center')
for v in range(0,261,50): text(sx(v),474,f'{v}°',8,MUTED,align='center' if 0<v<250 else ('left' if v==0 else 'right'))
para(M,492,'<b>u</b> = 95th percentile of the UP readings, <b>d</b> = 5th percentile of the DOWN readings (outliers ignored). The gap between them is split 30% / 40% / 30%: <b>up below u + 0.3·gap</b>, <b>down above d − 0.3·gap</b>, and the middle 40% keeps the last state.',size=10)
para(M,550,'A stiffer finger that reads up to 110° when raised gets <i>up below 122°</i>: with the default 90° line it would often sit in the KEEP zone and be misread.',size=10,color=MUTED)
section(600,'Check before you save')
xx=M
for name,score in [('fist',1.0),('1 finger',1.0),('2 fingers',0.98),('3 fingers',0.76),('4 fingers',0.94)]:
    lab=f'{name} {score*100:.0f}%'
    wdt=C.stringWidth(lab,'Arial-Bold',9.5)+18
    rect(xx,632,wdt,22,HexColor('#D7F0E3') if score>=0.9 else HexColor('#FBE8C8'),radius=5)
    text(xx+wdt/2,638,lab,9.5,INK,'Arial-Bold','center'); xx+=wdt+8
para(M,668,'Every collected frame is read again with the new lines. Under 90% (amber) that sign may still be misread: try again, or skip it. Fingers whose UP and DOWN readings overlap are flagged.',size=10)
box(M,708,CW,66,'Saved per hand','settings.json keeps both lines for every finger and the thumb. Settings > Calibrate shows them, and can reset to 90° / 140°.')

# V10: dynamics and the mixer.
new_page(10,'Strike harder, play louder; mix each hand','Velocity comes from how fast your fingers moved just before the sign. Each hand then has its own volume and reverb.',f'Handbook: dynamics {pg(3)}; strike speed {pg(13)}; mixing and reverb {pg(16)}')
gx,gy,gw,gh=M+34,160,240,160
line(gx,gy+gh,gx+gw,gy+gh,MUTED); line(gx,gy,gx,gy+gh,MUTED)
vx=lambda ms:gx+ms/500*gw; vy=lambda v:gy+gh-(v-0.3)/0.7*gh
for v in (0.3,0.5,0.7,0.9,1.0):
    line(gx-3,vy(v),gx,vy(v),MUTED); text(gx-6,vy(v)-4,f'{v:.1f}',8,MUTED,align='right')
for ms in (0,100,200,300,400,500): text(vx(ms),gy+gh+6,str(ms),8,MUTED,align='center')
pts=[(67,1.0),(133,0.79),(267,0.59),(467,0.45)]
poly([(vx(a),vy(b)) for a,b in pts],BLUE,1.6)
for a,b in pts: dot(vx(a),vy(b),3.2,ORANGE); text(vx(a)+6,vy(b)-12,f'{b:.2f}',8.5,INK)
text(gx+gw/2,gy+gh+20,'time to form the sign (ms)',9,MUTED,align='center')
text(gx-28,gy-14,'velocity',9,MUTED)
para(M+300,160,'<b>Fingers:</b> the fastest change in finger bend over the last 0.15 s (degrees per second). <b>Pump:</b> the hand\'s speed (hand lengths per second).',CW-300,9.5)
rect(M+300,236,CW-300,50,PALE,radius=5)
text(M+310,244,'strength = (speed − floor) ÷ scale',9.5,INK,'Arial-Bold')
text(M+310,262,'velocity = 0.3 + 0.7 × strength',9.5,INK,'Arial-Bold')
para(M+300,296,'The floor ignores tracking jitter, so a slow sign is soft. <b>i</b> turns dynamics off.',CW-300,9.5,color=MUTED)
section(360,'The mixer: volume and reverb per hand')
def node(x,y,w,h,label,fill=PALE,color=INK):
    rect(x,y,w,h,fill,radius=4); text(x+w/2,y+h/2-5,label,9,color,'Arial-Bold','center')
node(M,398,86,32,'Left hand',HexColor('#D8EBFA'),BLUE); node(M,488,86,32,'Right hand',HexColor('#FBE3D2'),ORANGE)
node(M+110,398,66,32,'Volume'); node(M+110,488,66,32,'Volume')
node(M+200,436,128,46,'Reverb',INK,white)
text(M+264,463,'4 combs → 2 all-pass',7.5,white,align='center')
arrow(M+86,414,M+108,414); arrow(M+86,504,M+108,504)
arrow(M+176,420,M+198,446); arrow(M+176,496,M+198,472)
text(M+170,432,'send',8,TEAL); text(M+170,480,'send',8,TEAL)
C.setFillColor(PALE); C.circle(M+372,H-459,14,stroke=0,fill=1); text(M+372,454,'+',12,INK,'Arial-Bold','center')
line(M+176,404,M+372,404,BLUE,1.2); arrow(M+372,404,M+372,443)
line(M+176,514,M+372,514,ORANGE,1.2); arrow(M+372,514,M+372,475)
text(M+260,394,'dry',8,MUTED); text(M+260,518,'dry',8,MUTED)
arrow(M+328,459,M+356,459); text(M+334,446,'× 1.4',8,MUTED)
node(M+398,442,48,34,'tanh'); arrow(M+386,459,M+396,459)
node(M+462,442,45,34,'Out',GREEN); arrow(M+446,459,M+460,459)
text(M+485,420,'song audio',7.5,MUTED,align='center'); arrow(M+485,430,M+485,440)
text(M+398,486,'soft clip',7.5,MUTED)
section(548,'What the reverb does to one click')
base=640
line(M,base,M+235,base,GRAY); line(M+272,base,W-M,base,GRAY)
for k in range(9):
    x=M+12+k*26; h=58*exp(-k*0.33)
    line(x,base,x,base-h,BLUE,2)
text(M,base+10,'comb filters: a train of echoes, each quieter and duller',9,MUTED)
rnd2=random.Random(5)
for k in range(70):
    x=M+282+k*3.2; h=50*exp(-k*0.045)*(0.35+0.65*rnd2.random())
    line(x,base,x,base-h,TEAL,1)
text(M+272,base+10,'all-pass filters: echoes smeared into a smooth wash',9,MUTED)
para(M,676,'Every delay (441 to 1,356 samples) is longer than one 256-sample audio block, so each block is computed with a few whole-array NumPy operations: fast enough for real time.',size=10)
para(M,722,'The song\'s own recording joins after the soft clip, since it is already mixed.',size=10,color=MUTED)

# V11: looper timing, MIDI files and hand sessions.
new_page(11,'Loop in time, keep it as MIDI','A metronome and count-in put you on the beat, quantise tidies what you played, and any performance can be saved as a MIDI file.',f'Handbook: recording {pg(6)}; MIDI files {pg(17)}; timing {pg(19)}')
lx=M+62; bw=(CW-62)/12
rect(lx,156,4*bw,118,PALE)
for hb in range(25):
    x=lx+hb*bw/2
    line(x,186,x,262,GRAY,0.8 if hb%2 else 1.2)
for b in range(12):
    x=lx+b*bw
    C.setFillColor(INK if b%4==0 else MUTED); C.circle(x,H-172,3.4 if b%4==0 else 2.2,stroke=0,fill=1)
text(M,167,'Click',9.5,INK,'Arial-Bold'); text(M,200,'Played',9.5,INK,'Arial-Bold'); text(M,240,'Quantised',9.5,INK,'Arial-Bold'); text(M,252,'1/8 grid',8,MUTED)
for start,length,col in [(4.3,0.8,SLOTC[0]),(5.6,0.5,SLOTC[1]),(7.15,1.2,SLOTC[2]),(9.9,0.6,SLOTC[3])]:
    q=round(start/0.5)*0.5
    rect(lx+start*bw,194,length*bw,16,col,radius=3)
    rect(lx+q*bw,234,length*bw,16,col,radius=3)
    arrow(lx+start*bw,212,lx+q*bw,232,MUTED)
for b,lab in [(0,'count-in'),(4,'bar 1'),(8,'bar 2')]: text(lx+b*bw+3,264,lab,8.5,TEAL if b else MUTED,'Arial-Bold')
para(M,286,'Each start moves to the nearest grid step; the note keeps its length. With the click or quantise on, the first take is rounded to whole bars, so the loop stays in time with the click.',size=10)
section(342,'A MIDI file of what you played')
lanes=[('Tempo','120 BPM, 4/4',[]),('Right hand','ch 1 · Piano',[(0.05,0.12),(0.2,0.1),(0.34,0.2),(0.6,0.12),(0.78,0.15)]),('Left hand','ch 2 · Strings',[(0.05,0.3),(0.4,0.3),(0.75,0.22)]),('Loop','ch 3-4',[(0.1,0.08),(0.3,0.08),(0.5,0.08),(0.7,0.08),(0.9,0.06)]),('Drums','ch 10 · GM kit',[(k/16,0.015) for k in range(16)])]
for i,(a,b,blips) in enumerate(lanes):
    y=374+i*24
    text(M,y+2,a,9.5,INK,'Arial-Bold'); text(M+72,y+3,b,8.5,MUTED)
    rect(M+165,y,CW-165,16,PALE,radius=3)
    for s0,ln in blips: rect(M+165+s0*(CW-165),y+3,ln*(CW-165),10,BLUE if i<3 else (TEAL if i==3 else ORANGE),radius=2)
    if not blips: text(M+175,y+3,'set tempo · time signature',8,MUTED)
para(M,500,'<b>F7</b> records everything you play live; <b>F8</b> saves the loop. Times are stored in ticks: <b>tick = seconds × BPM ÷ 60 × 480</b>. Velocities come from your strike speed, and each hand\'s instrument becomes a General MIDI program.',size=10)
section(574,'Hand sessions: replay without a camera')
for i,(a,b) in enumerate([('F5 record','Only the 21 points of each hand, 30 times a second.'),('.gmsession','Compressed text; about 20 KB per second; no images.'),('F6 / --demo','Replays in real time, looping.'),('Same pipeline','Fed to process() exactly like the camera.')]):
    x=M+i*129
    box(x,606,117,84,a,b)
    if i<3: arrow(x+118,648,x+127,648)
para(M,708,'Replay a misread sign with the debug view on, try a new setting on exactly the same movement, or show the instrument with no webcam: <b>--demo</b> plays a 20-second Band-mode performance.',size=10)

# V12: from a music file to a chart.
new_page(12,'Turn your own music into a chart','The program listens to the file: where the beats are, which chords sound and what the tune is. You check it by ear, then pick a chart.',f'Handbook: adding music {pg(5)}; music analysis {pg(20)}; music theory {pg(18)}')
steps=['Audio file','Spectrogram','Onsets','Tempo + beats','Notes','Song sheet']
sw=(CW-5*10)/6
for i,a in enumerate(steps):
    x=M+i*(sw+10)
    rect(x,152,sw,30,INK if i in (0,5) else PALE,radius=4)
    text(x+sw/2,162,a,8.5,white if i in (0,5) else INK,'Arial-Bold','center')
    if i<5: arrow(x+sw+1,167,x+sw+9,167)
ex,ey,ew,eh=M,206,236,90
line(ex,ey+eh,ex+ew,ey+eh,GRAY)
for k in range(17):
    x=ex+6+k*13.6
    h=[1.0,0.25,0.55,0.2][k%4]*eh*(0.85+0.15*((k*7)%3)/2)
    line(x,ey+eh,x,ey+eh-h,BLUE,2.2)
    if k%2==0: line(x,ey+eh+3,x,ey+eh+8,ORANGE,1.2)
para(ex,ey+eh+12,'<b>Onset envelope:</b> sudden increases in the spectrum (spectral flux). Orange ticks: the beat grid found.',ew,9)
ax=M+270; aw=CW-270
line(ax,ey+eh,ax+aw,ey+eh,GRAY)
curve=[]
for k in range(121):
    t=k/120*2.6
    v=0.45*exp(-((t-1)/0.07)**2)+0.95*exp(-((t-2)/0.07)**2)+0.25*exp(-((t-0.5)/0.06)**2)+0.08
    curve.append((ax+k/120*aw,ey+eh-v*eh))
poly(curve,TEAL,1.4)
for t,lab in [(1,'1 beat'),(2,'2 beats')]:
    x=ax+t/2.6*aw; line(x,ey+eh,x,ey+eh+5,INK); text(x,ey+eh+8,lab,8,INK,align='center')
para(ax,ey+eh+22,'<b>Autocorrelation:</b> how alike the envelope is to itself when shifted. A kick on beats 1 and 3 peaks at 2 beats; when the 1-beat pulse is also clear, the faster tempo wins.',aw,9)
section(384,'Notes from the spectrum')
names=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
vals=[0.95,0.08,0.18,0.06,0.8,0.12,0.05,0.85,0.07,0.2,0.06,0.1]
cbw=236/12
for k,(n,v) in enumerate(zip(names,vals)):
    rect(M+k*cbw,500-v*72,cbw-3,v*72,BLUE if v>0.5 else GRAY)
    text(M+k*cbw+(cbw-3)/2,504,n,7.5,MUTED,align='center')
text(M,412,'Chroma of one beat → C major',9,INK,'Arial-Bold')
para(ax,414,'<b>Chords:</b> each beat\'s 12 note energies are compared with 24 major and minor chord shapes. A Viterbi pass charges a small cost for every change, so passing melody notes don\'t make the chords flicker.<br/><b>Key:</b> the song\'s note totals against major and minor key profiles.<br/><b>Melody:</b> the highest strong pitch every half beat, since the tune usually sits on top.',aw,9.5)
section(540,'Check it by ear, then choose a chart')
for i,(a,b) in enumerate([('Listen with clicks','A rim click on every beat, louder on bar 1. Clicks drifting: fix the tempo. Steady but off: move bar 1.'),('Fix it, or tap it','±0.1 / ±1 / ×2 / ÷2 BPM; ±0.01 s / ±1 beat. Or tap Space on the beats: a straight line through your taps.'),('Pick a chart','Melody, Chords or Rhythm; Easy, Normal or Hard. A preview shows the pads and first bars.')]):
    box(M+i*173,572,161,104,a,b)
para(M,690,'<b>Melody:</b> low notes on the left hand, high on the right, like a keyboard. <b>Chords:</b> one chord per sign. <b>Rhythm:</b> kick and snare on the left, hi-hat on the right.',size=10)
rect(M,732,CW,40,PALE,radius=6)
para(M+12,738,'Tempo, bar 1, key and chords are reliable with a steady beat; the melody is a starting point in a full mix. The sheet is plain text, so any note can be fixed.',CW-24,9.5)

# V13: navigation into the handbook and module map.
new_page(13,'Connect the pictures to your code','Read the visual idea first, then jump into the handbook for the implementation and theory.','Visual edition and handbook: 3 November 2026')
text(M,152,'CONCEPT',9,MUTED,'Arial-Bold')
text(M+245,152,'CODE OWNER',9,MUTED,'Arial-Bold')
rows=[('Get a recent camera image','camera.py'),('Measure, confirm and time hand signs','gestures.py'),('Fit thresholds to your hands','calibration.py'),('Choose notes and dispatch events','gesture_music.py'),('Draw the window; mouse and keys','ui.py'),('Generate sound; mix and reverb','sound_engine.py / drums.py'),('Send external instrument messages','midi_out.py'),('Write and read MIDI files','midi_file.py'),('Record and replay timed actions','looper.py'),('Record and replay hand sessions','session.py / handmodel.py'),('Parse charts, schedule and judge','game.py / songs/'),('Analyse music; write song sheets','audio_analysis.py / songmaker.py'),('Remember settings and presets','settings.py'),('Blur the preview; record a demo','background.py / capture.py')]
for i,(a,b) in enumerate(rows):
    y=174+i*21;line(M,y-5,W-M,y-5)
    text(M,y,a,9.5);text(M+245,y,b,9,BLUE)
section(482,'Jump into the full handbook')
refs=[('Play: window, signs, sounds',3,'Window, signs, modes, instruments, dynamics, presets'),('Calibrate and record',4,'Calibration, looper, MIDI files, hand sessions'),('Understand the architecture',10,'Data flow, events, threads and every module'),('Understand gesture geometry',13,'Angles, thresholds, calibration fit, strike speed'),('Understand sound',16,'Partials, envelopes, mixer and reverb'),('Understand music analysis',20,'Tempo, beats, chords and melody from a recording')]
LINKS=[]
for i,(title,sec,desc) in enumerate(refs):
    y=512+i*35
    page=SECTION[sec]
    text(M,y,title,11,BLUE,'Arial-Bold')
    text(W-M,y,f'Handbook p. {page}',9,MUTED,align='right')
    text(M,y+16,desc,9,MUTED)
    LINKS.append((M,H-y-28,W-M,H-y+4,page))
para(M,735,f'The next page begins the complete handbook. Its printed page numbers are unchanged; PDF page numbers are {NV} higher.',size=10)
C.save()

# Preserve every handbook page, add bookmarks and clickable cross-references.
writer=PdfWriter()
primer=PdfReader(TMP/'visual-primer.pdf')
original=PdfReader(SOURCE)
assert len(primer.pages)==NV==len(P)
for page in primer.pages: writer.add_page(page)
for page in original.pages: writer.add_page(page)
for i,title in enumerate(P):writer.add_outline_item(f'V{i+1}  {title}',i)
parent=writer.add_outline_item('Complete handbook',NV)
for h in HEADINGS:
    page=SECTION[int(h.split('.')[0]) if h[0].isdigit() else h]
    writer.add_outline_item(f'{h} - p. {page}',NV+page-1,parent=parent)
from pypdf.annotations import Link
for x1,y1,x2,y2,page in LINKS:
    target=NV+page-1
    annotation=writer.add_annotation(NV-1,Link(rect=(x1,y1,x2,y2),target_page_index=target))
    # Local PDF destinations must point to the actual page object.
    annotation['/Dest'][0]=writer.pages[target].indirect_reference
writer.add_metadata({'/Title':'Gesture Music Handbook - Visual Edition','/Author':'rayangmendrofa','/Subject':f'{NV} illustrated concept pages followed by the complete handbook'})
with DEST.open('wb') as f:writer.write(f)
check=PdfReader(DEST)
assert len(check.pages)==len(original.pages)+NV
for i,p in enumerate(original.pages):assert check.pages[i+NV].extract_text()==p.extract_text()
assert [check.get_page_number(a.get_object()['/Dest'][0].get_object())+1 for a in check.pages[NV-1]['/Annots']]==[NV+l[4] for l in LINKS]
print(f'Created {DEST} ({len(check.pages)} pages; handbook {len(original.pages)} pages preserved)')
