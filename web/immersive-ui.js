// Native dialogs provide focus containment, Escape, and return-to-trigger behavior.
const dialogs=[...document.querySelectorAll('.orchard-dialog')];
let menuTrigger;
document.querySelectorAll('[data-dialog]').forEach(button=>button.addEventListener('click',()=>{
  const wasOpen=dialogs.some(dialog=>dialog.open);
  if(!wasOpen)menuTrigger=button;
  dialogs.forEach(dialog=>{if(dialog.open)dialog.close();});
  const dialog=document.getElementById(button.dataset.dialog);
  dialog.showModal();
}));
for(const dialog of dialogs){
  dialog.querySelector('[data-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});
  dialog.addEventListener('close',()=>{if(!dialogs.some(d=>d.open))menuTrigger?.focus();});
}
const notice=document.getElementById('notice');
new MutationObserver(()=>document.querySelectorAll('[data-notice]').forEach(element=>{
  element.textContent=notice.textContent;element.classList.toggle('visible',notice.classList.contains('visible'));
})).observe(notice,{childList:true,attributes:true,subtree:true});
