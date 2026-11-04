export type HistoryEntry = {id:string, status:string, stage?:string, visual_test?:boolean, product_name?:string};

export function chooseInitialRun(history:HistoryEntry[]):string|undefined {
  return (history.find(h=>h.status==='running'&&!h.visual_test)
    || history.find(h=>h.status==='review'&&!h.visual_test)
    || history.find(h=>!h.visual_test)
    || history[0])?.id;
}
