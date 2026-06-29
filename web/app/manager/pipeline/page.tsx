import { redirect } from "next/navigation";

// The pipeline + reliability views are now tabs on the Home dashboard.
export default function ManagerPipelinePage() {
  redirect("/manager");
}
