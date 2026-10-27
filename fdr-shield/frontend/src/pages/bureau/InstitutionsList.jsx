import { useQuery } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/PageStates';

export default function InstitutionsList() {
  const query = useQuery({
    queryKey: ['institutions'],
    queryFn: () => client.get('/institutions').then((response) => response.data),
  });

  return (
    <section>
      <h1 className="mb-2 text-3xl font-bold">Institutions</h1>
      <p className="mb-6 text-slate-600">Registered AICTE institutions and their deposit records.</p>
      {query.isLoading ? <LoadingState label="Loading institutions" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} label="Could not load institutions" />
          : !query.data?.length ? <EmptyState title="No institutions found">Registered institutions will appear here.</EmptyState>
            : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.map((institution) => (
              <article key={institution.id} className="rounded-xl border bg-white p-5">
                <p className="text-xs font-semibold text-cyan-700">{institution.aicte_id}</p>
                <h2 className="mt-1 text-lg font-semibold">{institution.name}</h2>
                <p className="mt-1 text-sm text-slate-500">{institution.state} · {institution.head_name}</p>
                <p className="mt-4 text-sm">{institution.contact_email}</p>
              </article>
            ))}</div>}
    </section>
  );
}
