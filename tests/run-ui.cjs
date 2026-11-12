/* Isolated local Chrome; no account profile, backend, source checkout or providers. */
const {chromium}=require('playwright');
const path=require('path');
const {pathToFileURL}=require('url');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  for(const name of process.argv.slice(2).length?process.argv.slice(2):['task-desk-ui','project-ui','sources-ui','team-ui','changes-ui','budget-ui']){
   const page=await browser.newPage({viewport:{width:1280,height:1000},colorScheme:'light'});
   await page.route(/^https?:/,route=>route.abort());
   const check=(await import(pathToFileURL(path.resolve('tests/'+name+'.mjs')))).default;
   console.log(JSON.stringify({suite:name,...await check(page,pathToFileURL(path.resolve(process.env.INTERSPACE_UI||'app/ui/index.html')).href)}));
   await page.close();
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
