import { redirect } from "next/navigation";

// Principle authoring now lives inside the Knowledge corpus it feeds, as the
// "Add principle" dialog.
export default function ManagerIngestionPage() {
  redirect("/manager/knowledge");
}
