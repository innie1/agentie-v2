(()=>{
  if(window.__agentieGroupOfflineCache)return;window.__agentieGroupOfflineCache=true;
  const nativeFetch=window.fetch.bind(window);
  const PREFIX='agentie.groupchat.cache.v1:';
  const LIST_KEY=PREFIX+'list';
  const threadKey=id=>PREFIX+'thread:'+String(id||'');

  function pathOf(input){
    try{
      if(typeof input==='string')return new URL(input,location.href).pathname;
      if(input&&typeof input.url==='string')return new URL(input.url,location.href).pathname;
    }catch(_){ }
    return '';
  }
  function methodOf(input,init){return String(init?.method||input?.method||'GET').toUpperCase()}
  function threadId(path){const m=String(path||'').match(/^\/platform\/agent-chats\/([^/]+)$/);return m?decodeURIComponent(m[1]):''}
  function isList(path){return path==='/platform/agent-chats'}
  function isThread(path){return !!threadId(path)}
  function store(key,value){try{localStorage.setItem(key,JSON.stringify({saved_at:Date.now(),value}))}catch(_){ }}
  function load(key){try{const raw=localStorage.getItem(key);if(!raw)return null;const parsed=JSON.parse(raw);return parsed&&parsed.value?parsed.value:null}catch(_){return null}}
  function response(value){return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json','X-Agentie-Group-Cache':'1'}})}
  function saveThread(value){if(value&&value.id&&Array.isArray(value.messages))store(threadKey(value.id),value)}
  async function inspectAndStore(res,path,method){
    if(!res?.ok)return;
    try{
      const data=await res.clone().json();
      if(isList(path)&&method==='GET'){
        store(LIST_KEY,data);
        for(const item of data.items||[])primeThread(item?.id);
      }else if((isThread(path)||/\/platform\/agent-chats\/[^/]+\/messages$/.test(path))&&data?.id){
        saveThread(data);
      }
    }catch(_){ }
  }
  async function primeThread(id){
    if(!id)return;
    try{
      const res=await nativeFetch(`/platform/agent-chats/${encodeURIComponent(id)}`,{cache:'no-store'});
      if(!res.ok)return;
      const data=await res.clone().json();
      saveThread(data);
    }catch(_){ }
  }
  function fallback(path,method){
    if(method!=='GET')return null;
    if(isList(path)){const cached=load(LIST_KEY);return cached?response(cached):null}
    const id=threadId(path);if(!id)return null;const cached=load(threadKey(id));return cached?response(cached):null
  }

  window.fetch=async function(input,init={}){
    const path=pathOf(input),method=methodOf(input,init),groupRequest=isList(path)||isThread(path)||/\/platform\/agent-chats\/[^/]+\/messages$/.test(path);
    if(!groupRequest)return nativeFetch(input,init);
    try{
      const res=await nativeFetch(input,init);
      if(res.ok){inspectAndStore(res,path,method);return res}
      return fallback(path,method)||res;
    }catch(err){
      const cached=fallback(path,method);
      if(cached)return cached;
      throw err;
    }
  };

  window.__agentieGroupCacheRead=id=>load(threadKey(id));
  window.__agentieGroupCacheList=()=>load(LIST_KEY);
})();
