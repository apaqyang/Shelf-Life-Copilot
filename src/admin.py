"""Small dependency-free management UI backed exclusively by the query API."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Shelf-Life Copilot · 租户管理</title><style>
body{font:15px system-ui;margin:0;background:#f5f7fa;color:#17202a}header{background:#17324d;color:white;padding:20px}
main{max-width:1100px;margin:auto;padding:24px}.bar{display:flex;gap:10px;flex-wrap:wrap}input,select,button{padding:9px}
button{background:#176b87;color:white;border:0;border-radius:4px}table{width:100%;border-collapse:collapse;margin-top:18px;background:white}
th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}.error{color:#a00}</style></head>
<body><header><h1>Shelf-Life Copilot</h1><div>多租户运营台</div></header><main>
<div class="bar"><input id="token" type="password" placeholder="API Bearer token"><button onclick="loadCustomers()">登录</button>
<select id="customer" onchange="loadView()"></select><select id="view" onchange="loadView()"><option value="batches">批次</option><option value="work-orders">工单</option></select></div>
<p id="message"></p><table><thead id="head"></thead><tbody id="body"></tbody></table></main><script>
const auth=()=>({'Authorization':'Bearer '+document.getElementById('token').value});
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function get(path){let r=await fetch(path,{headers:auth()});if(!r.ok)throw Error((await r.json()).detail||r.status);return r.json()}
function cells(values){return '<tr>'+values.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>'}
async function loadCustomers(){try{let d=await get('/api/customers'),s=document.getElementById('customer');s.innerHTML=d.items.map(x=>`<option value="${esc(x.customer_id)}">${esc(x.customer_id)} · ${esc(x.industry)}</option>`).join('');await loadView()}catch(e){message.textContent=e.message;message.className='error'}}
async function loadView(){let c=customer.value,v=view.value;if(!c)return;try{let d=await get(`/api/customers/${encodeURIComponent(c)}/${v}`);let work=v==='work-orders';head.innerHTML=work?'<tr><th>工单</th><th>批次</th><th>动作</th><th>状态</th></tr>':'<tr><th>批次</th><th>物料</th><th>库存</th><th>到期日</th></tr>';body.innerHTML=d.items.map(x=>work?cells([x.work_order_id,x.batch_id,x.action,x.status]):cells([x.batch_id,x.material_name,x.stock_qty+' '+x.unit,x.expiry_date])).join('');message.textContent=`${d.items.length} 条`;message.className=''}catch(e){message.textContent=e.message;message.className='error'}}
</script></body></html>"""


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_console() -> str:
    return _HTML
