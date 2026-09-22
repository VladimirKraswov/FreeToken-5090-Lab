const MAX_PROGRESS_OPERATIONS = 8

const trackedTools = new Set([
  "apply_patch",
  "bash",
  "edit",
  "task",
  "webfetch",
  "websearch",
  "write",
])

const sessions = new Map()

function stateFor(sessionID) {
  let state = sessions.get(sessionID)
  if (!state) {
    state = { operations: 0 }
    sessions.set(sessionID, state)
  }
  return state
}

function validateTodos(todos) {
  if (!Array.isArray(todos) || todos.length === 0) {
    throw new Error("Для нетривиальной задачи Todo не может быть пустым")
  }

  const unfinished = todos.filter((todo) => todo?.status !== "completed")
  const active = todos.filter((todo) => todo?.status === "in_progress")

  if (unfinished.length > 0 && active.length !== 1) {
    throw new Error(
      "Todo должен содержать ровно один текущий этап со статусом in_progress",
    )
  }

  if (unfinished.length === 0 && active.length !== 0) {
    throw new Error("Завершённый Todo не должен содержать in_progress")
  }
}

export const ProgressGuard = async () => ({
  "tool.definition": async (input, output) => {
    if (input.toolID === "todowrite") {
      output.description +=
        " Для существенной задачи обновляйте план на завершённых этапах: ровно один текущий этап in_progress. Маленькая задача или проверка только для чтения не требует плана."
    }

    if (input.toolID === "bash") {
      output.description +=
        " Указывайте обоснованный timeout для долгих команд. Тайм-аут проверки требует диагностики и не означает успех. Сохраняйте код завершения тестов; длительные серверы запускайте фоновым заданием."
    }
  },

  "tool.execute.before": async (input, output) => {
    const state = stateFor(input.sessionID)

    if (input.tool === "todowrite") {
      validateTodos(output.args?.todos)
      state.operations = 0
      return
    }

    // Progress advice must not prevent verification or deadlock a read-only
    // reviewer whose permissions intentionally forbid todowrite.
  },

  "tool.execute.after": async (input, output) => {
    if (!trackedTools.has(input.tool)) return
    const state = stateFor(input.sessionID)
    state.operations += 1
    if (state.operations >= MAX_PROGRESS_OPERATIONS) {
      state.operations = 0
      output.output +=
        "\n[Progress reminder] For substantial implementation work, refresh the current milestone and checkpoint when useful. Read-only review and small tasks do not require Todo or checkpoint writes. Continue the verification; this reminder does not block tools."
    }
  },

  "experimental.session.compacting": async (_input, output) => {
    output.context.push(
      "Preserve acceptance criteria, verified checks, Git state and the next action. If this task already has a Todo plan or checkpoint, preserve its current milestone and restore it when useful. Read-only reviewers must not write Todo or checkpoint files. Do not create a plan merely because compaction occurred.",
    )
  },
})
