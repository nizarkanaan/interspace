/* Project registry presentation: the project picker and project details. No filesystem or provider access. */
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
      form.onsubmit = event => {
        event.preventDefault();
        const value = {};
        for (const key of ['name','brief','priority','next_action']) value[key] = $(key==='name'?'project-name-input':'project-'+key).value;
        request('update_project', {project_id:project.id, ...value}).then(() => {
          const current = drafts.get(project.id);
          const unchanged = current && Object.keys(value).every(key => current[key] === value[key]);
          if (unchanged) drafts.delete(project.id);
          if ($('project-picker').value === project.id) $('metadata-status').textContent = drafts.has(project.id) ? 'Unsaved changes' : 'Saved on your machine';
        }).catch(() => {});
      };
    }
  }
  return {render};
})();
