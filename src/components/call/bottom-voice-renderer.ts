import type { BottomVoiceStyle } from "@/lib/bottom-voice-style";
// Canvas versions of the four approved bottom-edge design prototypes.
// Pulse columns express energy; they are not frequency-bin measurements.
function gradient(ctx: CanvasRenderingContext2D, w: number, state: string, alpha = 1) {
    const g = ctx.createLinearGradient(0, 0, w, 0);
    const colors = state === 'listening' ? ['130,244,255', '142,108,255', '130,244,255'] : ['255,216,107', '130,244,255', '255,123,213', '142,108,255'];
    g.addColorStop(0, 'rgba(142,108,255,0)');
    colors.forEach((c, i) => g.addColorStop(.14 + .72 * i / (colors.length - 1), 'rgba(' + c + ',' + alpha + ')'));
    g.addColorStop(1, 'rgba(142,108,255,0)');
    return g;
}
function base(ctx: CanvasRenderingContext2D, w: number, h: number, state: string) {
    ctx.globalCompositeOperation = 'source-over';
    ctx.strokeStyle = state === 'muted' ? '#81808c' : state === 'error' ? '#d4a67d' : gradient(ctx, w, state, .72);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    if (state === 'error')
        ctx.setLineDash([13, 8]);
    ctx.moveTo(0, h - 1);
    ctx.lineTo(w, h - 1);
    ctx.stroke();
    ctx.setLineDash([]);
}
function quiet(ctx: CanvasRenderingContext2D, w: number, h: number, state: string, time: number) {
    base(ctx, w, h, state);
    if (state === 'thinking') {
        const x = (Math.sin(time * .7) * .5 + .5) * w;
        const g = ctx.createLinearGradient(x - w * .2, 0, x + w * .2, 0);
        g.addColorStop(0, '#cbd7ff00');
        g.addColorStop(.5, '#e9dfff');
        g.addColorStop(1, '#cbd7ff00');
        ctx.strokeStyle = g;
        ctx.lineWidth = 2;
        ctx.shadowColor = '#ad91f7';
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.moveTo(Math.max(0, x - w * .2), h - 1);
        ctx.lineTo(Math.min(w, x + w * .2), h - 1);
        ctx.stroke();
        ctx.shadowBlur = 0;
    }
}
function ribbon(ctx: CanvasRenderingContext2D, w: number, h: number, amp: number, t: number, state: string) {
    const cy = h - 1, phase = t * 2.4;
    const env = (x: number) => Math.pow(Math.cos(Math.PI * x / 2), 2), main = (x: number) => cy - amp * env(x) * (.52 + .48 * Math.sin(x * 1.1 + phase));
    const colors = ['#FFD86B', '#FF7BD5', '#82F4FF', '#8E6CFF'], offsets = [-2.77, -.94, .94, 2.77];
    ctx.globalCompositeOperation = 'screen';
    for (let k = 0; k < 4; k++) {
        const p = new Path2D();
        for (let i = 0; i <= 120; i++) {
            const x = i / 60 - 1, px = (x + 1) * w / 2;
            if (i)
                p.lineTo(px, main(x));
            else
                p.moveTo(px, main(x));
        }
        for (let i = 120; i >= 0; i--) {
            const x = i / 60 - 1;
            p.lineTo((x + 1) * w / 2, cy - amp * 1.14 * env(x) * (.52 + .48 * Math.sin(x + phase + offsets[k])));
        }
        p.closePath();
        const g = ctx.createLinearGradient(0, cy - amp, 0, cy + amp);
        g.addColorStop(0, colors[k] + '08');
        g.addColorStop(.4, colors[k] + '70');
        g.addColorStop(.6, colors[k] + '58');
        g.addColorStop(1, colors[k] + '05');
        ctx.fillStyle = g;
        ctx.shadowColor = colors[k];
        ctx.shadowBlur = 18;
        ctx.fill(p);
        ctx.shadowBlur = 0;
        ctx.strokeStyle = colors[k] + '85';
        ctx.lineWidth = .8;
        ctx.stroke(p);
    }
    const p = new Path2D();
    for (let i = 0; i <= 120; i++) {
        const x = i / 60 - 1;
        if (i)
            p.lineTo((x + 1) * w / 2, main(x));
        else
            p.moveTo((x + 1) * w / 2, main(x));
    }
    ctx.strokeStyle = gradient(ctx, w, state, .9);
    ctx.lineWidth = 1.8;
    ctx.shadowColor = '#c9f9ff';
    ctx.shadowBlur = 9;
    ctx.stroke(p);
    ctx.shadowBlur = 0;
}
function aurora(ctx: CanvasRenderingContext2D, w: number, h: number, amp: number, t: number) {
    ctx.globalCompositeOperation = 'screen';
    const colors = ['#8E6CFF', '#82F4FF', '#FF7BD5', '#FFD86B'];
    for (let k = 0; k < 4; k++) {
        const cx = w * (.18 + k * .21 + .07 * Math.sin(t * .62 + k)), spread = w * (.19 + .03 * Math.cos(t * .4 + k));
        const p = new Path2D();
        p.moveTo(0, h);
        for (let x = 0; x <= w + 4; x += 4) {
            const z = (x - cx) / spread;
            const envelope = Math.exp(-z * z * 1.8);
            const height = amp * (.55 + .4 * Math.pow(Math.sin(t * .8 + k), 2)) * envelope;
            const y = h - 1 - height * (.8 + .2 * Math.sin(x / w * 5 + t + k));
            p.lineTo(x, y);
        }
        p.lineTo(w, h);
        p.closePath();
        const g = ctx.createLinearGradient(0, h - amp, 0, h);
        g.addColorStop(0, colors[k] + '00');
        g.addColorStop(.35, colors[k] + '0c');
        g.addColorStop(.76, colors[k] + '45');
        g.addColorStop(1, colors[k] + 'c0');
        ctx.fillStyle = g;
        ctx.shadowColor = colors[k];
        ctx.shadowBlur = 22;
        ctx.fill(p);
        ctx.shadowBlur = 0;
    }
}
function strings(ctx: CanvasRenderingContext2D, w: number, h: number, amp: number, t: number) {
    ctx.globalCompositeOperation = 'screen';
    const colors = ['#b8a5ff', '#82f4ff', '#f1e7ff'];
    for (let k = 0; k < 3; k++) {
        const p = new Path2D();
        for (let i = 0; i <= 140; i++) {
            const x = i / 140, env = Math.pow(Math.sin(Math.PI * x), 2);
            const y = h - 1 - amp * .72 * env * (.12 + .88 * Math.pow(Math.sin(x * 4.2 - t * 1.8 + k * .8), 2));
            if (i)
                p.lineTo(x * w, y);
            else
                p.moveTo(x * w, y);
        }
        ctx.strokeStyle = colors[k];
        ctx.globalAlpha = .35 + k * .22;
        ctx.lineWidth = k === 2 ? 1.3 : .8;
        ctx.shadowColor = colors[k];
        ctx.shadowBlur = k === 2 ? 8 : 4;
        ctx.stroke(p);
    }
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
}
function pulse(ctx: CanvasRenderingContext2D, w: number, h: number, amp: number, t: number, state: string) {
    ctx.globalCompositeOperation = 'screen';
    const n = Math.max(24, Math.floor(w / 7));
    const gap = w / n;
    ctx.fillStyle = gradient(ctx, w, state, .9);
    for (let i = 0; i < n; i++) {
        const x = (i + .5) / n, env = Math.pow(Math.sin(Math.PI * x), 1.15);
        const rhythm = .12 + .48 * Math.pow(Math.sin(i * .37 - t * 3.2), 2) + .4 * Math.pow(Math.sin(i * .19 + t * 1.9), 4);
        const height = Math.max(1.5, amp * env * rhythm * .86);
        ctx.beginPath();
        ctx.roundRect(i * gap + gap * .24, h - height, gap * .5, height, Math.min(1.4, height / 2));
        ctx.fill();
    }
}
export function paintBottomVoice(ctx: CanvasRenderingContext2D, width: number, height: number, style: BottomVoiceStyle, state: string, level: number, time: number) {
    ctx.clearRect(0, 0, width, height);
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";
    const baseAmplitude = Math.min(48, height * .72) * Math.pow(Math.max(0, level), .72);
    const amplitude = style === "aurora" ? Math.min(height * .82, baseAmplitude * 2.8) : baseAmplitude;
    if (amplitude < .3) {
        quiet(ctx, width, height, state, time);
        return;
    }
    ({ ribbon, aurora, strings, pulse }[style])(ctx, width, height, amplitude, time, state);
    base(ctx, width, height, state);
}
