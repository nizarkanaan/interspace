/* Project registry presentation. No filesystem or provider access. */
window.interspaceWorkspace = (() => {
  const $ = id => document.getElementById(id);
  const drafts = new Map();
  const node = (tag, text, parent) => {
    const element = document.createElement(tag);
    element.textContent = text;
    parent.append(element);
    return element;
  };
  function render(state, request, openProject) {
    const picker = $('project-picker');
    picker.replaceChildren();
    if (!state.projects.length) {
      node('option', 'Add your first project', picker).value = '';
    }
    for (const project of state.projects) node('option', project.name, picker).value = project.id;
    picker.value = state.project_id || '';
    picker.disabled = !state.projects.length;
    picker.onchange = () => openProject(picker.value);
    const overview = $('project-overview');
    overview.replaceChildren();
    for (const project of [...state.projects].sort((a,b) => ['high','normal','low'].indexOf(a.priority)-['high','normal','low'].indexOf(b.priority))) {
      const card = node('article', '', overview);
      card.className = 'project-card';
      node('span', project.priority+' priority', card).className = 'mono';
      node('h3', project.name, card);
      node('p', project.brief || 'Add a brief to give your Workspace Orchestrator context.', card);
      node('p', project.next_action ? 'Next: '+project.next_action : 'Next action not set.', card).className = 'muted';
      const latest = project.latest_run;
      node('small', latest ? 'Latest review · '+latest.stage.replaceAll('_',' ') : 'No review yet', card);
      if (project.has_pending_plan) node('small', ' · Proposal ready to inspect', card);
      const button = node('button', 'Open project →', card);
      button.onclick = () => openProject(project.id);
    }
    $('overview-empty').hidden = !!state.projects.length;
    const project = state.projects.find(p => p.id === state.project_id);
    $('project-settings').hidden = !project;
    if (project) {
      // Background progress never overwrites an unsaved metadata form.
      const draft = drafts.get(project.id) || project;
      for (const key of ['name','brief','priority','next_action']) $(key==='name'?'project-name-input':'project-'+key).value = draft[key];
      const form = $('project-form');
      form.oninput = () => {
        const value = {};
        for (const key of ['name','brief','priority','next_action']) value[key] = $(key==='name'?'project-name-input':'project-'+key).value;
        drafts.set(project.id, value);
        $('metadata-status').textContent = 'Unsaved changes';
      };
      $('metadata-status').textContent = drafts.has(project.id) ? 'Unsaved changes' : 'Saved on your machine';
      for (const control of form.elements) control.disabled = !!state.active;
      form.onsubmit = event => {
        event.preventDefault();
        const value = {};
        for (const key of ['name','brief','priority','next_action']) value[key] = $(key==='name'?'project-name-input':'project-'+key).value;
        request('update_project', {project_id:project.id, ...value}).then(() => {
          drafts.delete(project.id);
          if ($('project-picker').value === project.id) $('metadata-status').textContent = 'Saved on your machine';
        }).catch(() => {});
      };
    }
    const history = $('run-picker');
    history.replaceChildren();
    $('run-history').hidden = !state.runs.length;
    for (const run of state.runs) {
      node('option', run.goal.slice(0,90)+' · '+run.stage.replaceAll('_',' ')+' · '+run.id.slice(-6), history).value = run.id;
    }
    history.value = state.run?.id || '';
    history.onchange = () => request('select_run', {project_id:state.project_id, run_id:history.value}).catch(() => {});
  }
  return {render};
})();
