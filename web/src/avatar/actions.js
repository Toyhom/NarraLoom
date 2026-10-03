import {t} from './i18n.js';
// Sentence-local, audio-clock clips. No wall clock and no implicit looping.
export const actionLabels = {nod:t("点头"),shake_head:t("摇头"),tilt:t("歪头"),bow:t("鞠躬"),lean_forward:t("前倾"),lean_back:t("后仰"),sway:t("轻摆"),bounce:t("跃动")};
export const emotionLabels = {neutral:t("自然"),happy:t("开心"),sad:t("低落"),angry:t("生气"),soft:t("温柔")};

export function actionPose(cues = [], seconds = 0) {
  const pose = {headX:0,headY:0,tilt:0,bodyX:0,bodyY:0,bodyTilt:0,lean:0,active:[]};
  for (const cue of cues) {
    const duration = cue.duration_s, phase = (seconds - cue.start_s) / duration;
    if (!actionLabels[cue.name] || !Number.isFinite(phase) || duration <= 0 || phase <= 0 || phase >= 1) continue;
    const strength = Math.max(0,Math.min(1,cue.strength));
    // Squared sine starts and ends with zero velocity; finite clips return to rest.
    const pulse = Math.sin(Math.PI*phase)**2 * strength;
    const oscillation = Math.sin(4*Math.PI*phase) * pulse;
    pose.active.push(cue.name);
    switch(cue.name) {
      case 'nod': pose.headY += 2.4*pulse - 1.4*oscillation; break;
      case 'shake_head': pose.headX += 3.5*oscillation; break;
      case 'tilt': pose.tilt += .16*pulse; break;
      case 'bow': pose.headY += 2.1*pulse; pose.bodyY += .035*pulse; pose.lean -= .16*pulse; break;
      case 'lean_forward': pose.lean += .12*pulse; pose.headY += .7*pulse; break;
      case 'lean_back': pose.lean -= .09*pulse; pose.headY -= .65*pulse; break;
      case 'sway': pose.bodyTilt += .09*oscillation; pose.bodyX += .02*oscillation; break;
      case 'bounce': pose.bodyY -= .045*pulse; pose.lean += .025*oscillation; break;
    }
  }
  const limits = {headX:4,headY:3,tilt:.2,bodyX:.035,bodyY:.06,bodyTilt:.12,lean:.18};
  for(const [key,limit] of Object.entries(limits)) pose[key]=Math.max(-limit,Math.min(limit,pose[key]));
  return pose;
}
