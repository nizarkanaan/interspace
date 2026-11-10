// Presentation-only role templates. Declaring a tool never grants access to it.
(() => {
  const root = document.getElementById('ispace');
  const contracts = root.interspaceContracts;
  const departments = [
    {id:'discovery',name:'Discovery',look:'Scout'},
    {id:'research',name:'Research',look:'Researcher'},
    {id:'engineering',name:'Engineering',look:'Builder'},
    {id:'analysis',name:'Analysis',look:'Analyst'},
    {id:'review',name:'Review',look:'Reviewer'},
    {id:'writing',name:'Writing',look:'Writer'},
    {id:'operations',name:'Operations',look:'Coordinator'}
  ];
  const equipment = ['scanner','book','bulb','wrench','test','chart','clipboard','magnifier','pencil','slides','mail','calendar','notebook'];
  const definitions = [
    ['scout','Scout','discovery','SC','scanner','Monitor approved sites and collect relevant material.','Approved websites and extraction tools','Source collection with URLs and retrieval dates'],
    ['web-search','Web searcher','discovery','WS','magnifier','Find relevant pages and cross-check source quality.','Web search and approved pages','Ranked source list with relevance notes'],
    ['web-scraper','Web scraper','discovery','EX','notebook','Extract structured information from approved pages.','Selected URLs and extraction tools','Structured dataset with provenance and missing fields'],
    ['researcher','Researcher','research','RS','book','Search papers and build an evidence matrix.','Web search, selected PDFs, Zotero (read)','Evidence table with sources and unresolved questions'],
    ['literature','Literature reviewer','research','LR','notebook','Compare methods, assumptions and gaps across a paper collection.','Selected papers, Zotero (read)','Cited literature synthesis and comparison matrix'],
    ['ideation','Idea generator','research','IG','bulb','Propose testable ideas, then identify novelty and feasibility checks.','Project brief and selected evidence','Hypotheses with falsification criteria; novelty unverified'],
    ['builder','Builder','engineering','BU','wrench','Prepare code changes and reproducible experiments.','Selected repository, isolated runner','Patch, experiment manifest, logs and results'],
    ['debugger','Debugger','engineering','DB','magnifier','Reproduce failures and trace their root cause.','Selected repository and redacted logs','Reproduction, diagnosis and proposed fix'],
    ['tester','Test engineer','engineering','TE','test','Design regression checks for meaningful failure cases.','Selected repository and isolated test runner','Tests and observed pass/fail evidence'],
    ['experimenter','Experiment runner','analysis','ER','test','Prepare bounded experiments with matched scenarios and seeds.','Approved configurations and compute target','Experiment manifest and reproducible results'],
    ['data-analyst','Data analyst','analysis','DA','chart','Clean selected datasets and explain observed patterns.','Selected datasets and analysis runner','Analysis notebook, figures and limitations'],
    ['statistician','Statistician','analysis','ST','notebook','Check uncertainty, assumptions and statistical comparisons.','Selected data and experiment results','Statistical report with assumptions and uncertainty'],
    ['reviewer','Reviewer','review','RV','clipboard','Check methods, assumptions and evidence.','Project evidence and proposed outputs (read)','Review findings with severity and supporting evidence'],
    ['code-reviewer','Code reviewer','review','CR','wrench','Inspect code diffs for concrete defects without modifying them.','Selected diff, repository context and test evidence (read)','Located findings, coverage and evidence-backed verdict'],
    ['citation-checker','Citation checker','review','CC','magnifier','Verify that citations support the claims attributed to them.','Selected manuscript and cited sources (read)','Claim-to-source audit and unresolved citations'],
    ['reproducibility','Reproducibility reviewer','review','RR','test','Check whether methods and artifacts permit reproduction.','Experiment manifests, code and logs (read)','Reproducibility checklist and missing artifacts'],
    ['writer','Manuscript writer','writing','MW','pencil','Draft sections from approved claims and verified evidence.','Selected outline and cited evidence','Draft manuscript with source links and gaps marked'],
    ['slides','Slide designer','writing','SD','slides','Turn project findings into clear presentation slides.','Selected results, figures and audience brief','Slide outline, figures and speaker notes'],
    ['inbox','Inbox assistant','operations','IN','mail','Prioritize selected messages and prepare reply drafts.','Selected email scope; connection required','Priority briefing and unsent reply drafts'],
    ['calendar','Calendar assistant','operations','CA','calendar','Find scheduling conflicts and propose time blocks.','Selected calendar scope; connection required','Proposed schedule changes awaiting approval'],
    ['orchestrator','Orchestrator','operations','OR','bulb','Turn your goals into bounded plans, dispatch specialists and reconcile their results within the selected scope.','Scoped project state, role registry and authorized dispatch controls; runtime required','Execution plan, assignments, verified progress and decisions for you'],
    ['coordinator','Project coordinator','operations','PC','clipboard','Track dependencies, milestones and decisions across tasks.','Selected project tasks and decisions','Project plan, blockers and proposed next actions'],
    ['knowledge','Knowledge curator','operations','KC','book','Organize approved notes and connect sources to project knowledge.','Selected Obsidian vault, Notion pages or folders','Proposed note updates with provenance']
  ];
  const templates = new Map(definitions.map(([id,name,department,code,prop,instructions,tools,output]) =>
    [id,{id,name,department,code,prop,instructions,tools,output,look:departments.find(d=>d.id===department).look,contract:contracts.roles[id]}]));
  let customSequence = 0;
  function addCustom({name,department,prop,instructions,tools,output}) {
    const group = departments.find(d=>d.id===department);
    name = name.trim(); instructions = instructions.trim(); tools = tools.trim(); output = output.trim();
    if (!name || !instructions || !output || name.length>48 || instructions.length>800 || tools.length>200 || output.length>200)
      throw new Error('Give the role a name, instructions and expected output within the field limits.');
    if (!group || !equipment.includes(prop)) throw new Error('Choose a department and equipment from the available options.');
    if ([...templates.values()].some(role=>role.name.toLowerCase()===name.toLowerCase()))
      throw new Error('That role name already exists. Choose another name or add an agent from its template.');
    const id='custom-'+(++customSequence);
    const role={id,name,department,prop,instructions,tools:tools||'No tools requested',output,look:group.look,code:'C'+customSequence,custom:true};
    templates.set(id,role);
    return role;
  }
  root.interspaceRoles = {
    departments,equipment,contracts,
    list:()=>[...templates.values()],
    get:id=>templates.get(id),
    byName:name=>[...templates.values()].find(role=>role.name===name),
    addCustom
  };
})();
