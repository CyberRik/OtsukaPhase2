import { redirect } from "next/navigation";

// The standalone Workspace is now the right pane of the Manager home (Command
// Center), so this route just forwards there.
export default function ManagerWorkspacePage() {
  redirect("/manager");
}
