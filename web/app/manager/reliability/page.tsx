import { redirect } from "next/navigation";

// Reliability is now the "Flags" tab of the consolidated Pipeline page.
export default function ManagerReliabilityPage() {
  redirect("/manager/pipeline");
}
