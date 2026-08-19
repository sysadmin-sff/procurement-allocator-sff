import { Fragment, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { suppliersApi } from '../../api/suppliers';
import type {
  DeliveryPolicy,
  Office,
  OfficeCreate,
  Supplier,
  SupplierContact,
  SupplierContactCreate,
  SupplierDetail,
} from '../../api/types';
import { Button } from '../../components/Button';
import { ConfirmButton } from '../../components/ConfirmButton';
import { ErrorBanner } from '../../components/ErrorBanner';
import {
  DeliveryPolicyFields,
  deliveryPolicyToFormValues,
  formValuesToDeliveryPolicy,
  type DeliveryPolicyFormValues,
} from './DeliveryPolicyFields';
import styles from '../../components/CrudScreen.module.css';

type Status = 'loading' | 'ready' | 'error';

const NO_OFFICE = '__none__';

export function SupplierDetailPage() {
  const { supplierId } = useParams<{ supplierId: string }>();
  const [supplier, setSupplier] = useState<SupplierDetail | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  useEffect(() => {
    if (!supplierId) return;
    void load(supplierId);
  }, [supplierId]);

  async function load(id: string) {
    setStatus('loading');
    setLoadError(null);
    try {
      const data = await suppliersApi.get(id);
      setSupplier(data);
      setStatus('ready');
    } catch (err) {
      setLoadError(err);
      setStatus('error');
    }
  }

  async function refresh() {
    if (!supplierId) return;
    const data = await suppliersApi.get(supplierId);
    setSupplier(data);
  }

  if (!supplierId) {
    return <ErrorBanner error="Не указан поставщик." />;
  }

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <Link to="/suppliers" className={styles.backLink}>
          « Назад к поставщикам
        </Link>

        <div className={styles.header}>
          <h1 className={styles.title}>{supplier?.name ?? 'Поставщик'}</h1>
        </div>

        {actionError != null && <ErrorBanner error={actionError} />}

        {status === 'loading' && <div className={styles.loading}>Загрузка…</div>}

        {status === 'error' && <ErrorBanner error={loadError} />}

        {status === 'ready' && supplier && (
          <div className={styles.stack}>
            <BasicInfoSection
              supplier={supplier}
              onSaved={refresh}
              onError={setActionError}
            />
            <ContactsSection
              supplier={supplier}
              onChanged={refresh}
              onError={setActionError}
            />
            <OfficesSection
              supplier={supplier}
              onChanged={refresh}
              onError={setActionError}
            />
            <DeliveryPolicySection
              supplier={supplier}
              onSaved={refresh}
              onError={setActionError}
            />
            <CommentsSection
              supplier={supplier}
              onSaved={refresh}
              onError={setActionError}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------- Основная информация ---------------- */

interface BasicInfoFormValues {
  name: string;
  website: string;
  region: string;
  catalog_link: string;
  status: string;
  payment_terms: string;
  portal_url: string;
  contacts: string;
}

function toBasicInfoValues(supplier: Supplier): BasicInfoFormValues {
  return {
    name: supplier.name,
    website: supplier.website ?? '',
    region: supplier.region ?? '',
    catalog_link: supplier.catalog_link ?? '',
    status: supplier.status ?? '',
    payment_terms: supplier.payment_terms ?? '',
    portal_url: supplier.portal_url ?? '',
    contacts: supplier.contacts ?? '',
  };
}

function BasicInfoSection({
  supplier,
  onSaved,
  onError,
}: {
  supplier: Supplier;
  onSaved: () => Promise<void>;
  onError: (err: unknown) => void;
}) {
  const [values, setValues] = useState<BasicInfoFormValues>(() => toBasicInfoValues(supplier));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValues(toBasicInfoValues(supplier));
  }, [supplier]);

  function update<K extends keyof BasicInfoFormValues>(key: K, value: BasicInfoFormValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!values.name.trim()) return;

    const after: Supplier = {
      ...supplier,
      name: values.name.trim(),
      website: values.website.trim() || null,
      region: values.region.trim() || null,
      catalog_link: values.catalog_link.trim() || null,
      status: values.status.trim() || null,
      payment_terms: values.payment_terms.trim() || null,
      portal_url: values.portal_url.trim() || null,
      contacts: values.contacts.trim() || null,
    };

    setSaving(true);
    onError(null);
    try {
      await suppliersApi.update(supplier.id, supplier, after);
      await onSaved();
    } catch (err) {
      onError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className={styles.card} onSubmit={handleSubmit}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>Основная информация</div>
      </div>
      <div className={styles.cardPadded}>
        <div className={styles.formGrid}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-name">
              Название
            </label>
            <input
              id="basic-name"
              className={styles.input}
              value={values.name}
              onChange={(e) => update('name', e.target.value)}
              required
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-website">
              Веб-сайт
            </label>
            <input
              id="basic-website"
              className={styles.input}
              value={values.website}
              onChange={(e) => update('website', e.target.value)}
              placeholder="https://…"
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-region">
              Регион
            </label>
            <input
              id="basic-region"
              className={styles.input}
              value={values.region}
              onChange={(e) => update('region', e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-status">
              Статус
            </label>
            <input
              id="basic-status"
              className={styles.input}
              value={values.status}
              onChange={(e) => update('status', e.target.value)}
              placeholder="Активные закупки…"
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-catalog-link">
              Ссылка на прайс/каталог
            </label>
            <input
              id="basic-catalog-link"
              className={styles.input}
              value={values.catalog_link}
              onChange={(e) => update('catalog_link', e.target.value)}
              placeholder="https://drive.google.com/…"
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-payment-terms">
              Условия оплаты
            </label>
            <input
              id="basic-payment-terms"
              className={styles.input}
              value={values.payment_terms}
              onChange={(e) => update('payment_terms', e.target.value)}
              placeholder="NET 30"
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="basic-portal-url">
              Личный кабинет
            </label>
            <input
              id="basic-portal-url"
              className={styles.input}
              value={values.portal_url}
              onChange={(e) => update('portal_url', e.target.value)}
              placeholder="https://…"
            />
          </div>
          <div className={`${styles.field} ${styles.fieldFull}`}>
            <label className={styles.label} htmlFor="basic-contacts">
              Общий контакт/примечание
            </label>
            <input
              id="basic-contacts"
              className={styles.input}
              value={values.contacts}
              onChange={(e) => update('contacts', e.target.value)}
              placeholder="Email, телефон…"
            />
            <div className={styles.fieldHint}>
              Свободнотекстовое поле для общего контакта — не заменяет структурированные
              контакты ниже, существует параллельно с ними.
            </div>
          </div>
        </div>

        <div className={styles.formActions}>
          <Button type="submit" variant="primary" disabled={saving}>
            Сохранить
          </Button>
        </div>
      </div>
    </form>
  );
}

/* ---------------- Офисы ---------------- */

function OfficesSection({
  supplier,
  onChanged,
  onError,
}: {
  supplier: SupplierDetail;
  onChanged: () => Promise<void>;
  onError: (err: unknown) => void;
}) {
  const [newAddress, setNewAddress] = useState('');
  const [newRegion, setNewRegion] = useState('');
  const [adding, setAdding] = useState(false);

  async function handleAdd() {
    if (!newAddress.trim()) return;
    setAdding(true);
    onError(null);
    try {
      const payload: OfficeCreate = {
        address: newAddress.trim(),
        region: newRegion.trim() || null,
      };
      await suppliersApi.createOffice(supplier.id, payload);
      setNewAddress('');
      setNewRegion('');
      await onChanged();
    } catch (err) {
      onError(err);
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(office: Office) {
    onError(null);
    try {
      await suppliersApi.removeOffice(supplier.id, office.id);
      await onChanged();
    } catch (err) {
      onError(err);
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>Офисы</div>
      </div>
      <div className={styles.tableScroll}>
        <table className={`${styles.table} ${styles.tableFixed}`}>
          <colgroup>
            <col style={{ width: '44%' }} />
            <col style={{ width: '28%' }} />
            <col style={{ width: '160px' }} />
          </colgroup>
          <thead>
            <tr>
              <th>Адрес</th>
              <th>Регион</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {supplier.offices.map((office) => (
              <OfficeRow
                key={office.id}
                supplierId={supplier.id}
                office={office}
                onSaved={onChanged}
                onRemove={() => void handleRemove(office)}
                onError={onError}
              />
            ))}
            <tr>
              <td>
                <input
                  className={`${styles.input} ${styles.tableInput}`}
                  placeholder="Адрес офиса"
                  value={newAddress}
                  onChange={(e) => setNewAddress(e.target.value)}
                />
              </td>
              <td>
                <input
                  className={`${styles.input} ${styles.tableInput}`}
                  placeholder="Регион (необязательно)"
                  value={newRegion}
                  onChange={(e) => setNewRegion(e.target.value)}
                />
              </td>
              <td>
                <Button
                  variant="secondary"
                  disabled={!newAddress.trim() || adding}
                  onClick={() => void handleAdd()}
                >
                  + Добавить
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OfficeRow({
  supplierId,
  office,
  onSaved,
  onRemove,
  onError,
}: {
  supplierId: string;
  office: Office;
  onSaved: () => Promise<void>;
  onRemove: () => void;
  onError: (err: unknown) => void;
}) {
  async function handleAddressBlur(value: string) {
    if (value === office.address || !value.trim()) return;
    onError(null);
    try {
      await suppliersApi.updateOffice(supplierId, office.id, office, {
        ...office,
        address: value.trim(),
      });
      await onSaved();
    } catch (err) {
      onError(err);
    }
  }

  async function handleRegionBlur(value: string) {
    const normalized = value.trim() || null;
    if (normalized === office.region) return;
    onError(null);
    try {
      await suppliersApi.updateOffice(supplierId, office.id, office, {
        ...office,
        region: normalized,
      });
      await onSaved();
    } catch (err) {
      onError(err);
    }
  }

  return (
    <tr>
      <td>
        <input
          key={office.address}
          className={`${styles.input} ${styles.tableInput}`}
          defaultValue={office.address}
          onBlur={(e) => void handleAddressBlur(e.target.value)}
        />
      </td>
      <td>
        <input
          key={office.region ?? ''}
          className={`${styles.input} ${styles.tableInput}`}
          defaultValue={office.region ?? ''}
          onBlur={(e) => void handleRegionBlur(e.target.value)}
        />
      </td>
      <td>
        <div className={styles.actionsCell}>
          <ConfirmButton label="Удалить" onConfirm={onRemove} />
        </div>
      </td>
    </tr>
  );
}

/* ---------------- Контакты ---------------- */

interface ContactGroup {
  office: Office | null;
  contacts: SupplierContact[];
}

function groupContactsByOffice(
  contacts: SupplierContact[],
  offices: Office[],
): ContactGroup[] {
  const officeById = new Map(offices.map((o) => [o.id, o]));
  const groups: ContactGroup[] = offices.map((office) => ({
    office,
    contacts: contacts.filter((c) => c.office_id === office.id),
  }));
  const withoutOffice = contacts.filter(
    (c) => c.office_id === null || !officeById.has(c.office_id),
  );
  if (withoutOffice.length > 0 || groups.length === 0) {
    groups.push({ office: null, contacts: withoutOffice });
  }
  return groups;
}

function ContactsSection({
  supplier,
  onChanged,
  onError,
}: {
  supplier: SupplierDetail;
  onChanged: () => Promise<void>;
  onError: (err: unknown) => void;
}) {
  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newOfficeId, setNewOfficeId] = useState(NO_OFFICE);
  const [adding, setAdding] = useState(false);

  const groups = groupContactsByOffice(supplier.supplier_contacts, supplier.offices);

  async function handleAdd() {
    if (!newName.trim()) return;
    setAdding(true);
    onError(null);
    try {
      const payload: SupplierContactCreate = {
        name: newName.trim(),
        role: newRole.trim() || null,
        phone: newPhone.trim() || null,
        email: newEmail.trim() || null,
        office_id: newOfficeId === NO_OFFICE ? null : newOfficeId,
      };
      await suppliersApi.createContact(supplier.id, payload);
      setNewName('');
      setNewRole('');
      setNewPhone('');
      setNewEmail('');
      setNewOfficeId(NO_OFFICE);
      await onChanged();
    } catch (err) {
      onError(err);
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(contact: SupplierContact) {
    onError(null);
    try {
      await suppliersApi.removeContact(supplier.id, contact.id);
      await onChanged();
    } catch (err) {
      onError(err);
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>Контакты</div>
      </div>
      <div className={styles.tableScroll}>
        <table className={`${styles.table} ${styles.tableFixed}`}>
          <colgroup>
            <col style={{ width: '15%' }} />
            <col style={{ width: '18%' }} />
            <col style={{ width: '13%' }} />
            <col style={{ width: '16%' }} />
            <col style={{ width: '18%' }} />
            <col style={{ width: '200px' }} />
          </colgroup>
          <thead>
            <tr>
              <th>Имя</th>
              <th>Роль</th>
              <th>Телефон</th>
              <th>Email</th>
              <th>Офис</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <Fragment key={group.office?.id ?? '__none__'}>
                <tr className={styles.categoryRow}>
                  <td colSpan={6} className={styles.categoryCell}>
                    {group.office ? group.office.address : 'Без офиса'}
                  </td>
                </tr>
                {group.contacts.length === 0 && (
                  <tr>
                    <td colSpan={6} className={styles.muted}>
                      Контактов нет
                    </td>
                  </tr>
                )}
                {group.contacts.map((contact) => (
                  <ContactRow
                    key={contact.id}
                    supplierId={supplier.id}
                    contact={contact}
                    offices={supplier.offices}
                    onSaved={onChanged}
                    onRemove={() => void handleRemove(contact)}
                    onError={onError}
                  />
                ))}
              </Fragment>
            ))}
            <tr>
              <td>
                <input
                  className={`${styles.input} ${styles.tableInput}`}
                  placeholder="Имя"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
              </td>
              <td>
                <input
                  className={`${styles.input} ${styles.tableInput}`}
                  placeholder="Роль"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                />
              </td>
              <td>
                <input
                  className={`${styles.input} ${styles.tableInput}`}
                  placeholder="Телефон"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                />
              </td>
              <td>
                <input
                  className={`${styles.input} ${styles.tableInput}`}
                  placeholder="Email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                />
              </td>
              <td>
                <select
                  className={`${styles.select} ${styles.tableInput}`}
                  value={newOfficeId}
                  onChange={(e) => setNewOfficeId(e.target.value)}
                >
                  <option value={NO_OFFICE}>— без офиса —</option>
                  {supplier.offices.map((office) => (
                    <option key={office.id} value={office.id}>
                      {office.address}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <Button
                  variant="secondary"
                  disabled={!newName.trim() || adding}
                  onClick={() => void handleAdd()}
                >
                  + Добавить
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ContactRow({
  supplierId,
  contact,
  offices,
  onSaved,
  onRemove,
  onError,
}: {
  supplierId: string;
  contact: SupplierContact;
  offices: Office[];
  onSaved: () => Promise<void>;
  onRemove: () => void;
  onError: (err: unknown) => void;
}) {
  async function saveField(after: SupplierContact) {
    onError(null);
    try {
      await suppliersApi.updateContact(supplierId, contact.id, contact, after);
      await onSaved();
    } catch (err) {
      onError(err);
    }
  }

  function handleTextBlur(field: 'name' | 'role' | 'phone' | 'email', value: string) {
    const normalized = field === 'name' ? value.trim() : value.trim() || null;
    if (normalized === contact[field] || (field === 'name' && !value.trim())) return;
    void saveField({ ...contact, [field]: normalized });
  }

  function handleOfficeChange(value: string) {
    const office_id = value === NO_OFFICE ? null : value;
    if (office_id === contact.office_id) return;
    void saveField({ ...contact, office_id });
  }

  return (
    <tr>
      <td>
        <input
          key={contact.name}
          className={`${styles.input} ${styles.tableInput}`}
          defaultValue={contact.name}
          onBlur={(e) => handleTextBlur('name', e.target.value)}
        />
      </td>
      <td>
        <input
          key={contact.role ?? ''}
          className={`${styles.input} ${styles.tableInput}`}
          defaultValue={contact.role ?? ''}
          onBlur={(e) => handleTextBlur('role', e.target.value)}
        />
      </td>
      <td>
        <input
          key={contact.phone ?? ''}
          className={`${styles.input} ${styles.tableInput}`}
          defaultValue={contact.phone ?? ''}
          onBlur={(e) => handleTextBlur('phone', e.target.value)}
        />
      </td>
      <td>
        <input
          key={contact.email ?? ''}
          className={`${styles.input} ${styles.tableInput}`}
          defaultValue={contact.email ?? ''}
          onBlur={(e) => handleTextBlur('email', e.target.value)}
        />
      </td>
      <td>
        <select
          className={`${styles.select} ${styles.tableInput}`}
          value={contact.office_id ?? NO_OFFICE}
          onChange={(e) => handleOfficeChange(e.target.value)}
        >
          <option value={NO_OFFICE}>— без офиса —</option>
          {offices.map((office) => (
            <option key={office.id} value={office.id}>
              {office.address}
            </option>
          ))}
        </select>
      </td>
      <td>
        <div className={styles.actionsCell}>
          <ConfirmButton label="Удалить" onConfirm={onRemove} />
        </div>
      </td>
    </tr>
  );
}

/* ---------------- Условия доставки ---------------- */

function DeliveryPolicySection({
  supplier,
  onSaved,
  onError,
}: {
  supplier: Supplier;
  onSaved: () => Promise<void>;
  onError: (err: unknown) => void;
}) {
  const [values, setValues] = useState<DeliveryPolicyFormValues>(() =>
    deliveryPolicyToFormValues(supplier.delivery_policy),
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValues(deliveryPolicyToFormValues(supplier.delivery_policy));
  }, [supplier]);

  function update<K extends keyof DeliveryPolicyFormValues>(
    key: K,
    value: DeliveryPolicyFormValues[K],
  ) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const delivery_policy: DeliveryPolicy = formValuesToDeliveryPolicy(values);
    const after: Supplier = { ...supplier, delivery_policy };

    setSaving(true);
    onError(null);
    try {
      await suppliersApi.update(supplier.id, supplier, after);
      await onSaved();
    } catch (err) {
      onError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className={styles.card} onSubmit={handleSubmit}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>Условия доставки</div>
      </div>
      <div className={styles.cardPadded}>
        <div className={styles.formGrid}>
          <DeliveryPolicyFields values={values} onChange={update} idPrefix="detail-delivery" />
        </div>
        <div className={styles.formActions}>
          <Button type="submit" variant="primary" disabled={saving}>
            Сохранить
          </Button>
        </div>
      </div>
    </form>
  );
}

/* ---------------- Комментарии ---------------- */

function CommentsSection({
  supplier,
  onSaved,
  onError,
}: {
  supplier: Supplier;
  onSaved: () => Promise<void>;
  onError: (err: unknown) => void;
}) {
  const [comments, setComments] = useState(supplier.comments ?? '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setComments(supplier.comments ?? '');
  }, [supplier]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const normalized = comments.trim() || null;
    if (normalized === supplier.comments) return;

    const after: Supplier = { ...supplier, comments: normalized };
    setSaving(true);
    onError(null);
    try {
      await suppliersApi.update(supplier.id, supplier, after);
      await onSaved();
    } catch (err) {
      onError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className={styles.card} onSubmit={handleSubmit}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>Комментарии</div>
      </div>
      <div className={styles.cardPadded}>
        <textarea
          className={styles.textarea}
          style={{ width: '100%', minHeight: '160px' }}
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="История заметок: изменения цен, минимальные суммы заказа, дедлайны приёма заказов…"
        />
        <div className={styles.formActions}>
          <Button type="submit" variant="primary" disabled={saving}>
            Сохранить
          </Button>
        </div>
      </div>
    </form>
  );
}

