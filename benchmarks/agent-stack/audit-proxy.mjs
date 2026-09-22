import http from 'node:http';
import {appendFileSync, readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
const root=resolve(import.meta.dirname), upstream=new URL(process.env.UPSTREAM || 'http://127.0.0.1:1919');
http.createServer((req,res)=>{
 const chunks=[];let bytes=0;
 req.on('data',c=>{bytes+=c.length;if(bytes>64*1024*1024)req.destroy();else chunks.push(c);});
 req.on('end',()=>{
  const body=Buffer.concat(chunks);let data={};try{data=JSON.parse(body)}catch{}
  let trial='unknown';try{trial=readFileSync(root+'/active-trial','utf8').trim()}catch{}
  const start=Date.now();const record={trial,start:new Date(start).toISOString(),path:req.url,request_bytes:bytes,sha256:createHash('sha256').update(body).digest('hex'),model:data.model,temperature:data.temperature,top_p:data.top_p,top_k:data.top_k,max_tokens:data.max_tokens,reasoning_effort:data.reasoning_effort,reasoning:data.reasoning,chat_template_kwargs:data.chat_template_kwargs,tools:data.tools?.map(t=>t.function?.name||t.name),messages:data.messages?.length,prior_reasoning_messages:data.messages?.filter(m=>m.role==='assistant'&&m.reasoning_content).length,system_chars:data.messages?.filter(m=>m.role==='system'||m.role==='developer').reduce((n,m)=>n+JSON.stringify(m.content).length,0)};
  const out=http.request({hostname:upstream.hostname,port:upstream.port,path:req.url,method:req.method,headers:{...req.headers,host:upstream.host,authorization:'Bearer local'}}, incoming=>{
   record.status=incoming.statusCode;res.writeHead(incoming.statusCode,incoming.headers);
   let pending='';let first=false;
   incoming.on('data',chunk=>{
    res.write(chunk);pending+=chunk.toString('utf8');
    const lines=pending.split('\n');pending=lines.pop();
    for(const line of lines){if(!line.startsWith('data: '))continue;try{
     const event=JSON.parse(line.slice(6));const choice=event.choices?.[0],delta=choice?.delta;
     if(!first&&(delta?.content||delta?.reasoning_content||delta?.tool_calls)){first=true;record.ttft_s=(Date.now()-start)/1000;}
     if(record.first_action_s==null&&(delta?.content||delta?.tool_calls))record.first_action_s=(Date.now()-start)/1000;
     if(event.usage)record.usage=event.usage;if(choice?.finish_reason)record.finish_reason=choice.finish_reason;
    }catch{}}
   });
   incoming.on('end',()=>{record.elapsed_s=(Date.now()-start)/1000;appendFileSync(root+'/results/wire.jsonl',JSON.stringify(record)+'\n');res.end();});
  });
  out.on('error',e=>{record.error=e.message;appendFileSync(root+'/results/wire.jsonl',JSON.stringify(record)+'\n');if(!res.headersSent)res.writeHead(502);res.end('upstream unavailable');});
  res.on('close',()=>{if(!res.writableEnded)out.destroy();});out.end(body);
 });
}).listen(18319,'127.0.0.1',()=>console.log('audit proxy listening 127.0.0.1:18319'));
