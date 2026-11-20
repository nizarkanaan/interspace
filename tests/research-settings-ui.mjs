/* Settings → Research sources and the citation_checker routing role, against a fake bridge only
   (docs/superpowers/specs/research/credentials.md): no backend, Keychain, network or real key. */
import {install,requests,assert,text,fit,FAKE_KEY,FAKE_EMAIL} from './research-fixture.mjs';
export default async function check(page,url){
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await install(page,url);
 const settings=page.locator('#research-settings');
 const item=name=>settings.locator('.research-source[data-source='+name+']');
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('#research-settings .research-source').length===5);

 // One row per source: title, what it needs, optional or required, status; literal detail text.
 assert((await text(settings.locator('h2'))).includes('Research sources'),'Heading missing');
 const ss=await text(item('semantic_scholar'));
 assert(ss.includes('Semantic Scholar')&&ss.includes('Optional: your API key')&&ss.includes('Ready')&&ss.includes('Shared pool: often throttled'),'Semantic Scholar row: '+ss);
 assert((await text(item('arxiv'))).includes('Nothing to enter')&&await item('arxiv').locator('input').count()===0,'arXiv asks for a credential');
 const up=await text(item('unpaywall'));
 assert(up.includes('Required: your email address')&&up.includes('Needs your email address')&&!up.includes('Optional'),'Unpaywall not marked required: '+up);
 assert((await text(item('crossref'))).includes('Literal <img src=x onerror="window.pwned=1"> detail')&&await settings.locator('img').count()===0,'Detail inserted as markup');
 // The email goes to that service as its contact; keys stay in the Keychain and never reach agents.
 assert((await text(item('crossref'))).includes('Your email goes to Crossref with each request, as the contact address')&&(await text(item('unpaywall'))).includes('Your email goes to Unpaywall'),'Email contact note missing');
 assert(ss.includes('Keychain')&&ss.includes('never shown again or given to agents'),'Key privacy note missing');
 // Help links: https only; a javascript: or http: address gets no link.
 const hrefs=await settings.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')));
 assert(hrefs.length===3&&hrefs.every(h=>h.startsWith('https://')),'Help links: '+JSON.stringify(hrefs));
 assert(await item('semantic_scholar').getByRole('link',{name:/Get a free key from Semantic Scholar/}).count()===1,'Get a free key link missing');
 assert(await item('crossref').locator('a').count()===0&&await item('unpaywall').locator('a').count()===0,'Unsafe help link shown');
 assert(await item('arxiv').getByRole('link',{name:/About this service from arXiv/}).count()===1,'arXiv help link wording');

 // Keys: a password field, never pre-filled; invalid values never leave the page.
 const key=item('semantic_scholar').locator('input');
 assert(await key.getAttribute('type')==='password'&&await key.inputValue()==='','Key field not a blank password field');
 assert(await item('crossref').locator('input').getAttribute('type')==='email','Email field type');
 await key.fill('short');await item('semantic_scholar').getByRole('button',{name:'Save',exact:true}).click();
 assert((await requests(page,'research_credential_set')).length===0,'Short key sent');
 assert((await key.evaluate(i=>i.validationMessage)).includes('8 to 256'),'Key validation message');
 await item('unpaywall').locator('input').fill('not-an-email');await item('unpaywall').getByRole('button',{name:'Save',exact:true}).click();
 assert((await requests(page,'research_credential_set')).length===0,'Bad email sent');

 // What is typed survives other rows re-rendering (a Test on another source), and is not sent by it.
 await item('openalex').locator('input').fill('typed-but-not-saved-1');
 await item('arxiv').getByRole('button',{name:'Test arXiv',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#research-settings .research-source[data-source=arxiv]').textContent.includes('Test call succeeded.'));
 assert(await item('openalex').locator('input').inputValue()==='typed-but-not-saved-1','Typed key lost on re-render');
 assert(JSON.stringify(await requests(page,'research_test'))===JSON.stringify([{source:'arxiv'}]),'research_test params');
 await item('openalex').locator('input').fill('');

 // Save by keyboard: exact params, field cleared, the key never appears in the page, Replace afterwards.
 await key.fill(FAKE_KEY);await key.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#research-settings .research-source[data-source=semantic_scholar]').textContent.includes('Saved in your Keychain'));
 assert(JSON.stringify(await requests(page,'research_credential_set'))===JSON.stringify([{source:'semantic_scholar',value:FAKE_KEY}]),'Set params');
 assert(await key.inputValue()==='','Key field not cleared after save');
 const page1=await page.evaluate(()=>document.documentElement.outerHTML+[...document.querySelectorAll('input,textarea')].map(i=>i.value).join('|'));
 assert(!page1.includes(FAKE_KEY),'Key shown back in the page');
 assert(await item('semantic_scholar').getByRole('button',{name:'Replace',exact:true}).count()===1,'Replace not offered');
 assert((await key.getAttribute('placeholder')).includes('Saved'),'Saved placeholder missing');
 assert((await text(item('semantic_scholar').locator('label'))).includes('replacement API key'),'Replacement label');

 // Email save; a failed save shows the error, not the value.
 const mail=item('crossref').locator('input');
 await page.evaluate(()=>{window.rFixture.failNext.research_credential_set='Keychain not available. Open Interspace.app to save keys.';});
 await mail.fill(FAKE_EMAIL);await item('crossref').getByRole('button',{name:'Save',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#research-settings .research-source[data-source=crossref] .error-text'));
 assert((await text(item('crossref'))).includes('Keychain not available')&&await mail.inputValue()==='','Failed save');
 await mail.fill(FAKE_EMAIL);await mail.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#research-settings .research-source[data-source=crossref]').textContent.includes('Saved in your Keychain'));
 const sets=await requests(page,'research_credential_set');
 assert(sets.length===3&&sets[2].source==='crossref'&&sets[2].value===FAKE_EMAIL,'Email set params: '+JSON.stringify(sets));
 assert(!(await page.evaluate(()=>document.documentElement.outerHTML)).includes(FAKE_EMAIL),'Email shown back');

 // A failed test shows its detail as text.
 await item('openalex').getByRole('button',{name:'Test OpenAlex',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#research-settings .research-source[data-source=openalex]').textContent.includes('Test failed'));
 assert((await text(item('openalex'))).includes('<b>rate limited</b>')&&await settings.locator('b').count()===0,'Test detail markup');

 // Remove asks first; Cancel returns focus; Remove by keyboard sends the exact request.
 await item('semantic_scholar').getByRole('button',{name:'Remove your Semantic Scholar API key',exact:true}).click();
 assert((await text(item('semantic_scholar'))).includes('Remove your Semantic Scholar API key from this Mac’s Keychain?'),'Remove confirmation');
 assert((await requests(page,'research_credential_delete')).length===0,'Removed without confirmation');
 await item('semantic_scholar').getByRole('button',{name:'Cancel',exact:true}).click();
 assert(await page.evaluate(()=>document.activeElement?.id)==='research-remove-semantic_scholar','Cancel focus');
 await page.keyboard.press('Enter');
 assert(await page.evaluate(()=>document.activeElement?.id)==='research-remove-confirm-semantic_scholar','Confirm focus');
 await page.keyboard.press('Enter');
 await page.waitForFunction(()=>document.querySelector('#research-settings .research-source[data-source=semantic_scholar]').textContent.includes('Removed from your Keychain'));
 assert(JSON.stringify(await requests(page,'research_credential_delete'))===JSON.stringify([{source:'semantic_scholar'}]),'Delete params');
 assert(await item('semantic_scholar').getByRole('button',{name:'Save',exact:true}).count()===1,'Save not back after removal');

 // Routing: the citation checker is a read role listed with the others, and saved with them.
 const route=page.locator('.route-row[data-role=citation_checker]');
 assert(await route.count()===1&&(await text(route)).includes('Citation checker')&&(await text(route)).includes('Read role: checks references'),'Citation checker routing row');
 assert(await page.locator('#route-citation_checker-provider').inputValue()==='codex','Citation checker default provider');
 await page.locator('#route-citation_checker-provider').selectOption('claude');
 await page.getByRole('button',{name:'Save defaults',exact:true}).click();
 await page.waitForFunction(()=>window.rFixture.requests.some(r=>r.method==='routing_update'));
 const routing=(await requests(page,'routing_update'))[0].routing;
 assert(routing.roles.citation_checker.provider==='claude'&&routing.roles.researcher.provider==='codex','Routing update: '+JSON.stringify(routing.roles));

 // A load failure says so.
 await page.evaluate(()=>{window.rFixture.failNext.research_sources='Research sources could not be loaded.';});
 await page.locator('[data-view=tasks]').click();await page.locator('[data-view=settings]').click();
 await page.waitForFunction(()=>document.querySelector('#research-settings .error-text')?.textContent.includes('could not be loaded'));
 await page.locator('[data-view=tasks]').click();await page.locator('[data-view=settings]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#research-settings .research-source').length===5&&!document.querySelector('#research-settings .error-text'));

 const fits=await fit(page,'research-settings',null,true);
 assert(!(await page.evaluate(()=>window.pwned)),'Script ran');
 assert(!errors.length,'Page errors: '+errors.join(' | '));
 return {checks:'one row per source with title, need, optional/required, status, literal detail; email-as-contact and Keychain notes; https-only Get a free key links; blank password key field, email field; key/email validation before sending; typed key kept across re-render; exact set/test/delete params by keyboard; field cleared and key/email never shown back; failed save and failed test as text; Remove confirmation with focus; citation_checker routing row saved; load error recovery; light/dark 320-1280 fit',responsiveStates:fits.length};
}
