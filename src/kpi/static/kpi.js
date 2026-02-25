function fold(id){
  const b=document.querySelector(`[data-nid="${id}"] .tog`);if(!b)return;
  const s=b.classList.toggle('shut');
  document.querySelectorAll(`.p-${id}`).forEach(r=>{
    if(s){r.classList.add('hid');const t=r.querySelector('.tog');if(t&&!t.classList.contains('shut')){const sid=r.dataset.nid;if(sid)fold(sid)}}
    else if(!r.id||!r.id.startsWith('dw-'))r.classList.remove('hid')
  });
}
function td2(nid){const e=document.getElementById('dw-'+nid);if(e)e.classList.toggle('hid')}
