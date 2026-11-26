// Pure eligibility logic, shared by button state and its visible explanation.
export function runDisabledReason(state, user) {
  if (!user) return 'Sign in to continue.';
  if (state.running) return 'A response is already being prepared.';
  if (state.chatMode && user.chat_enabled) return '';
  if (!user.analysis_enabled) return 'GIS analysis requires an available isolated worker. Contact the administrator.';
  if (!state.project) return 'Select a project from the files sidebar to start GIS chat.';
  if (!user.isolated_analysis_enabled && state.activeRun && !state.activeRun.done && state.activeRun.project_id !== state.project.id)
    return 'Another project is using the analysis engine. Wait for it to finish.';
  return '';
}
