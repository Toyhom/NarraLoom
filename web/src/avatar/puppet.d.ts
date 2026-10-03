export class PuppetStage {
  constructor(canvas:HTMLCanvasElement,onStatus:(status:string)=>void);
  active:boolean; loaded:boolean; closeup:boolean; motionEvidence:{speechFrames:number;maxJointDelta:number;maxMouth:number;maxBodyDelta:number;maxExpression:number;actionFrames:Record<string,number>};
  load(character:{profile:Record<string,unknown>;asset_base:string}):Promise<void>;
  setMode(mode:string):void;setPerformance(frame:unknown,face:unknown):void;dispose():void;
}
