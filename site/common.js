// Shared formatting helpers. All figures come from data.json; none are written in the HTML.
const nf=(x,d=2)=>x==null?'n/a':x.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const pc=(x,d=1)=>x==null?'n/a':(100*x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d})+'%';
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const dt=s=>{const [y,m,d]=s.slice(0,10).split('-');return `${+d} ${MON[+m-1]} ${y}`};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const tag=s=>`<span class="tag ${s==='VERIFIED'?'':'ip'}">${esc(s)}</span>`;
const src=(u,t='source')=>`<a href="${esc(u)}" target="_blank" rel="noopener">${t}</a>`;
// a range collapses to one value only when both ends print identically
const rng=(a,b,f)=>f(a)===f(b)?f(a):f(a)+' – '+f(b);
