import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { marked } from 'marked';

const sidebar = ['Inbox','Tasks','Projects','Memory','Settings'];

function App() {
  const [view,setView]=useState('Inbox');
  const [tasks,setTasks]=useState<any[]>([]);
  const [messages,setMessages]=useState<string[]>(['# Local Ops Assistant\nReady.']);

  useEffect(()=>{ fetchTasks(); },[]);
  const fetchTasks=()=>fetch('http://127.0.0.1:8765/tasks').then(r=>r.json()).then(setTasks).catch(()=>{});
  const runTidy=async()=>{
    const res=await fetch('http://127.0.0.1:8765/tasks',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tool:'inbox_triage',payload:{limit:25,apply:false}})});
    const data=await res.json();
    setMessages(m=>[...m,`Started task: ${data.task_id}`]);
    fetchTasks();
  }

  return <div style={{display:'grid',gridTemplateColumns:'220px 1fr 360px',height:'100vh',fontFamily:'Inter, sans-serif'}}>
    <aside style={{borderRight:'1px solid #ddd',padding:12}}>{sidebar.map(s=><div key={s} onClick={()=>setView(s)} style={{padding:8,cursor:'pointer',fontWeight:view===s?700:400}}>{s}</div>)}</aside>
    <main style={{padding:16,overflow:'auto'}}>
      <h2>{view}</h2>
      {view==='Inbox' && <>
        <button onClick={runTidy}>Tidy my inbox</button>
        <p>Heuristics-first triage queue with confidence and approve/reject hooks.</p>
      </>}
      {view==='Tasks' && <pre>{JSON.stringify(tasks,null,2)}</pre>}
      {view==='Memory' && <p>Thread-level operational memory scaffold in SQLite.</p>}
    </main>
    <section style={{borderLeft:'1px solid #ddd',padding:16,overflow:'auto'}}>
      <h3>Assistant</h3>
      {messages.map((m,i)=><div key={i} dangerouslySetInnerHTML={{__html:marked.parse(m) as string}} />)}
      <h4>Activity</h4>
      <ul><li>heuristics hit</li><li>cache hit</li><li>Claude escalation</li><li>invite handling</li><li>move operations</li></ul>
    </section>
  </div>
}

createRoot(document.getElementById('root')!).render(<App />);
