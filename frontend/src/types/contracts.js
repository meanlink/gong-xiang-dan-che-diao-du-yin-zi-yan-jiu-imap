/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,chain_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,approved:boolean,briefing:Object,counts:Object}} ResearchChain */
/** @typedef {{id:number,key:string,name:string,lag:number,threshold:number,status:string,result:Object,error:string,generation:number}} ChainNode */
export {};
