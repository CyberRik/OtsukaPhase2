"use client";

import { useParams } from "next/navigation";
import { AccountView } from "@/components/account/account-view";

export default function ManagerAccountPage() {
  const { id } = useParams<{ id: string }>();
  return <AccountView customerId={id} role="manager" />;
}
