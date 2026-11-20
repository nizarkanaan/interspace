/* Isolated local Chrome; no account profile, source checkout or providers. live-ui runs the real backend with a fake runtime. */
const {chromium}=require('playwright');
const path=require('path');
const {pathToFileURL}=require('url');
const fs=require('fs');
// review-ui belongs to the review and merge stream; it runs once tests/review-ui.mjs exists.
const SUITES=['task-desk-ui','project-ui','agent-ui','team-card-ui','subagents-ui','providers-ui','live-ui','e2e-ui','hardening-ui','research-settings-ui','research-cards-ui','research-task-ui','corpus-ui','display-ui','research-e2e-ui',...(fs.existsSync(path.resolve('tests/review-ui.mjs'))?['review-ui']:[])];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  for(const name of process.argv.slice(2).length?process.argv.slice(2):SUITES){
   const page=await browser.newPage({viewport:{width:1280,height:1000},colorScheme:'light'});
   await page.route(/^https?:/,route=>route.abort());
   const check=(await import(pathToFileURL(path.resolve('tests/'+name+'.mjs')))).default;
   console.log(JSON.stringify({suite:name,...await check(page,pathToFileURL(path.resolve(process.env.INTERSPACE_UI||'app/ui/index.html')).href)}));
   await page.close();
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
