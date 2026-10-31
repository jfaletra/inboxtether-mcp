'use strict';
const $=id=>document.getElementById(id);
let csrf='', discovery=null, plan=null, planFingerprint='', complete=false, currentConfig=null, connectorTemplate='', clientValid=false, submittedConnection=null, installedConnection=null, installationStarted=false;
function showError(error){
 const message=$('error');
 message.textContent=error.message||'Setup could not continue. No automatic retry was made.';
 message.hidden=false;
 message.focus({preventScroll:true});
 message.scrollIntoView({behavior:'auto',block:'center'});
}
function clearError(){$('error').hidden=true;}
async function api(path,value){const response=await fetch(path,{method:value===undefined?'GET':'POST',credentials:'same-origin',headers:value===undefined?{}:{'Content-Type':'application/json','X-InboxTether-CSRF':csrf},...(value===undefined?{}:{body:JSON.stringify(value)})});const result=await response.json();if(!response.ok||result.error)throw(result.error||new Error('The local installer could not be reached.'));return result;}
function screen(n){clearError();for(let i=1;i<=3;i++){$('screen'+i).hidden=i!==n;$('step'+i).classList.toggle('done',i<n);if(i===n)$('step'+i).setAttribute('aria-current','step');else $('step'+i).removeAttribute('aria-current');}window.scrollTo({top:0,behavior:'smooth'});}
function textList(id,rows){const el=$(id);el.replaceChildren();for(const text of rows){const li=document.createElement('li');li.textContent=text;el.append(li);}}
function selectOptions(id,rows,defaultValue){const el=$(id);el.replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent='Choose an existing folder';el.append(empty);for(const row of rows){const opt=document.createElement('option');opt.value=row.path;opt.textContent=row.path;el.append(opt);}if(rows.some(x=>x.path===defaultValue))el.value=defaultValue;}
function folders(){const rows=discovery.folders;const drafts=rows.filter(f=>f.flags.some(x=>x.toLowerCase()==='\\drafts'));selectOptions('draftsPath',drafts,drafts.length===1?drafts[0].path:'');$('folderMappings').replaceChildren();for(const name of ['INBOX','Industry','Marketing','Orders','Suppliers','Review']){const label=document.createElement('label');label.textContent=name==='INBOX'?'Source Inbox':name;const select=document.createElement('select');select.id='map'+name;label.append(select);$('folderMappings').append(label);selectOptions(select.id,rows,name==='INBOX'?discovery.inbox_path:name);}}
function featureVisibility(){for(const name of ['drafts','organizer']){$(name+'Settings').hidden=!$(name).checked;$(name).closest('.feature').classList.toggle('selected',$(name).checked);}$('tlsSettings').hidden=!$('organizer').checked;plan=null;}
function featureValues(){const mailboxes={};for(const n of ['INBOX','Industry','Marketing','Orders','Suppliers','Review'])mailboxes[n]=$('map'+n).value;return{drafts:$('drafts').checked,organizer:$('organizer').checked,draft_ack:$('draftAck').checked,drafts_path:$('draftsPath').value,mailboxes,organizer_login:$('organizerLogin').value.trim(),review_origin:$('reviewOrigin').value.trim(),certificate_file:$('certificateFile').value.trim(),certificate_key_file:$('certificateKeyFile').value.trim(),linux_user:$('linuxUser').value.trim(),owner_username:$('ownerUsername').value.trim()};}
function clearPasswords(){for(const name of ['password','organizerPassword','ownerPassword','ownerConfirmation'])$(name).value='';}
function clientView(){
 const client=$('client').value,where=$('location').value,target=$('sshTarget').value.trim();
 $('sshTargetLabel').hidden=where==='local';
 clientValid=where==='local'||/^[A-Za-z0-9_][A-Za-z0-9_.@+-]{0,254}$/.test(target);
 const before={claude:'Choose Claude Desktop now. After installation is verified, download and run its one-time connector on your computer.', 'chatgpt-desktop':'Choose your supported desktop client now. After verified installation, use the saved stdio configuration in that client.', 'chatgpt-web':'ChatGPT web needs a separately configured supported plugin or Secure MCP Tunnel. This installer provides stdio only and does not create that connection.', other:'Choose a compatible MCP stdio client now. Connection instructions and downloads appear after verified installation.'};
 $('clientGuidance').textContent=before[client]+(where==='ssh'?' Existing SSH host-key trust and key-based access are prerequisites.':'');
 $('downloadClaude').hidden=client!=='claude';$('claudeCommand').hidden=client!=='claude';
 const web=client==='chatgpt-web';
 if(complete&&installedConnection){
  currentConfig=installedConnection.configuration;
  $('clientConfig').textContent=JSON.stringify(currentConfig,null,2);
  $('clientGuidance').textContent='These connection settings were fixed when installation started. Use the completed installation’s connector below.';
  if(web)$('clientConnectionStatus').textContent='AI client connection: not configured by this wizard. ChatGPT web requires a separately owner-configured supported hosted transport. No desktop-helper download can establish that web connection.';
 }
 for(const id of ['copyConfig','downloadConfig','downloadClaude'])$(id).disabled=!complete||!installedConnection;
 if(!complete&&!installationStarted)$('install').disabled=!$('confirmInstall').checked||!clientValid;
}
function lockConnection(locked){for(const id of ['client','location','sshTarget','backToFeatures','backToEmail'])$(id).disabled=locked;}
function completedConfig(){
 if(!complete||!installedConnection){showError({message:'Install InboxTether and wait for verification before downloading or copying its connector.'});return null;}
 return installedConnection.configuration;
}
async function bootstrap(){try{connectorTemplate=await (await fetch('/connect_claude.py')).text();const ticket=location.hash.slice(1);const r=await api('/api/session',ticket?{ticket}:{});csrf=r.csrf;history.replaceState(null,'','/');const status=await api('/api/status');$('linuxUser').value=status.default_linux_user||'';if(status.running){screen(3);poll();}}catch(e){showError(e);$('setupAccessHelp').hidden=false;$('testConnection').disabled=true;}}
$('connectForm').addEventListener('submit',async event=>{event.preventDefault();clearError();$('testConnection').disabled=true;$('testConnection').textContent='Checking secure connection…';$('toConfigure').disabled=true;$('connectionStatus').hidden=true;try{const value={connection:{host:$('host').value.trim(),port:Number($('port').value),account:$('account').value.trim(),login:$('login').value.trim()},password:$('password').value};discovery=await api('/api/connect',value);$('connectionStatus').textContent='Secure sign-in verified · Inbox accessible · '+discovery.folders.length+' existing folders found';$('connectionStatus').hidden=false;$('toConfigure').disabled=false;folders();}catch(e){showError(e);}finally{$('password').value='';$('mailPasswordRetry').hidden=false;$('testConnection').disabled=false;$('testConnection').textContent='Test connection';}});
for(const id of ['host','account','login','port'])$(id).addEventListener('input',()=>{$('toConfigure').disabled=true;$('connectionStatus').hidden=true;});
$('toConfigure').addEventListener('click',()=>screen(2));$('backToEmail').addEventListener('click',()=>screen(1));$('backToFeatures').addEventListener('click',()=>screen(2));
for(const name of ['drafts','organizer'])$(name).addEventListener('change',featureVisibility);
$('featuresForm').addEventListener('submit',async event=>{event.preventDefault();clearError();$('validateFeatures').disabled=true;$('validateFeatures').textContent='Checking configuration…';try{const value={features:featureValues(),organizer_password:$('organizerPassword').value,owner_password:$('ownerPassword').value,owner_confirmation:$('ownerConfirmation').value};const r=await api('/api/configure',value);plan=r.plan;planFingerprint=r.fingerprint;$('featurePasswordRetry').hidden=true;$('planPreview').textContent=JSON.stringify(plan,null,2);$('planFingerprint').textContent=planFingerprint;const f=plan.features;const rows=['Reader · secure, non-marking access'];if(f.drafts)rows.push('Drafts · '+f.drafts_path+' · client approval before saves');if(f.organizer)rows.push('Organizer · five verified folders · filing disabled','Dedicated owner approval · '+f.review_origin);rows.push('Fixed launch access for Linux login '+f.linux_user);rows.push(...plan.actions);textList('planSummary',rows);$('sshTarget').placeholder=f.linux_user+'@your-server';$('confirmInstall').checked=false;$('install').disabled=true;clientView();screen(3);}catch(e){if(['certificate','linux_user'].includes(e.code))$('linuxUser').closest('details').open=true;$('featurePasswordRetry').hidden=false;showError({message:(e.message||'Configuration could not be validated.')+' Password fields were cleared for your security. Re-enter the Organizer application password and both owner passphrase fields before trying again.'});}finally{clearPasswords();$('validateFeatures').disabled=false;$('validateFeatures').textContent='Validate and continue →';}});
for(const name of ['client','location','sshTarget'])$(name).addEventListener(name==='sshTarget'?'input':'change',clientView);
$('confirmInstall').addEventListener('change',()=>{if(!installationStarted)$('install').disabled=!$('confirmInstall').checked||!clientValid;});
$('install').addEventListener('click',async()=>{
 if(installationStarted)return;
 clearError();let sent=false;lockConnection(true);$('install').disabled=true;
 try{
  submittedConnection=await api('/api/client',{client:$('client').value,location:$('location').value,target:$('sshTarget').value.trim()});
  sent=true;installationStarted=true;
  await api('/api/install',{fingerprint:planFingerprint,confirmation:'INSTALL_SELECTED_FEATURES'});
  $('confirmationLabel').hidden=true;$('installProgress').hidden=false;poll();
 }catch(e){
  if(!sent){lockConnection(false);clientView();showError(e);}
  else{showError({message:'The installation request could not be confirmed. Do not repeat it. Check the protected installation receipt before recovery; connector downloads remain unavailable.'});}
 }
});
async function poll(){
 try{
  const r=await api('/api/status');$('installProgress').textContent=r.stage;
  if(r.error){showError(r.error);$('installProgress').textContent='Stopped. Review the protected installation receipt before another attempt. No connector is available.';return;}
  if(r.result&&!r.running){
   const bound=r.result.client_connection;
   if(r.result.installed!==true||!bound||!submittedConnection||JSON.stringify(bound.configuration)!==JSON.stringify(submittedConnection.configuration)){
    showError({message:'The completed installation’s connection settings could not be verified. Connector downloads remain unavailable. Check the protected installation receipt; do not repeat installation.'});return;
   }
   installedConnection=JSON.parse(JSON.stringify(bound));complete=true;
   $('title3').textContent='InboxTether installed successfully.';
   $('finishIntro').textContent='Server installation and checks are complete. Next, download the saved connector and connect your AI client on your computer.';
   $('summaryTitle').textContent='InboxTether installed successfully';$('installBadge').textContent='Verified';
   $('clientSettingsTitle').textContent='Saved connection settings';$('connectionBeforeHelp').textContent='These settings belong to the completed installation. Its saved connector is available below; the AI-client connection is still not verified by this wizard.';
   $('planSummary').hidden=true;$('install').hidden=true;$('installProgress').hidden=true;$('confirmationLabel').hidden=true;
   $('finalChecks').hidden=false;textList('checkResults',r.result.checks);textList('manualSteps',[...($('client').value==='claude'?[]:bound.manual_steps),...r.result.manual_requirements]);
   lockConnection(true);clientView();$('connectorStep').hidden=false;
   clearPasswords();
   $('closedMessage').textContent='Installation verified. AI client connection is a separate next step. Keep this page open until you have saved the connector.';
   try{await api('/api/finish',{});$('closedMessage').textContent='Installation verified. The temporary installer is closed. Keep this page open to download the saved connector; your AI client is not verified by this wizard.';}
   catch(e){showError({message:'Installation is verified, but the temporary installer could not confirm closure. Do not reinstall. Keep this page open for its saved connector and ask your operator to check the temporary listener.'});}
   $('connectorTitle').focus({preventScroll:true});$('connectorStep').scrollIntoView({behavior:'auto',block:'start'});return;
  }
  setTimeout(poll,900);
 }catch(e){showError({message:'The temporary installer connection was lost. Do not repeat installation blindly; check its protected receipt or use the documented recovery procedure. Connector downloads remain unavailable until verified completion.'});}
}
$('downloadClaude').addEventListener('click',()=>{const config=completedConfig();if(!config)return;const source=connectorTemplate.replace('"__INBOXTETHER_ENTRY_JSON__"',JSON.stringify(JSON.stringify(config)));const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([source],{type:'text/plain'}));a.download='connect_inboxtether_claude.py';a.click();URL.revokeObjectURL(a.href);});
$('copyConfig').addEventListener('click',async()=>{const config=completedConfig();if(!config)return;try{await navigator.clipboard.writeText(JSON.stringify(config,null,2));$('copyConfig').textContent='Copied';}catch(e){showError({message:'Select and copy the verified configuration shown below, or use Download JSON.'});}});
$('downloadConfig').addEventListener('click',()=>{const config=completedConfig();if(!config)return;const blob=new Blob([JSON.stringify(config,null,2)+'\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='inboxtether-client.json';a.click();URL.revokeObjectURL(a.href);});
featureVisibility();clientView();bootstrap();
